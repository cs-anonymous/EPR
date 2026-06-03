#!/usr/bin/env python3
"""Train full-parameter EPR SFT across 6 rounds without reloading.

Rounds: S1 -> S2 -> S3 -> Astar1 -> Astar2 -> Astar3
Each sample has 'input' (score + interpretation) and 'output' (performance MIDI).
Loss is computed only on the output portion.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from contextlib import nullcontext
from pathlib import Path

import torch
from torch import nn
import torch.distributed as dist
from datasets import load_dataset
from torch.utils.data import DataLoader
from torch.utils.data.distributed import DistributedSampler
from transformers import AutoModelForCausalLM, AutoTokenizer, get_scheduler, set_seed
from transformers.trainer import get_model_param_count
from transformers.trainer_pt_utils import get_parameter_names
from transformers.training_args import TrainingArguments

# ---------- distributed helpers ----------
def is_dist() -> bool:
    return dist.is_available() and dist.is_initialized()

def rank() -> int:
    return dist.get_rank() if is_dist() else 0

def world_size() -> int:
    return dist.get_world_size() if is_dist() else 1

def is_main() -> bool:
    return rank() == 0

def barrier() -> None:
    if is_dist():
        dist.barrier()

def unwrap_model(model: torch.nn.Module) -> torch.nn.Module:
    return model.module if hasattr(model, "module") else model

def save_manifest(output_dir: Path, payload: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "train_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

# ---------- token counting (same as build script) ----------
import re
TOKEN_RE = re.compile(r"<[^>]+>")

def count_tokens(tokenizer, text: str) -> int:
    tag_count = len(TOKEN_RE.findall(text))
    plain = TOKEN_RE.sub("", text)
    return tag_count + len(tokenizer(plain, add_special_tokens=False)["input_ids"])

# ---------- collator ----------
class SFTCollator:
    """Collator that concatenates input + output, masking input from labels."""
    def __init__(self, tokenizer, max_length: int):
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __call__(self, features):
        inputs = [feature["input"] for feature in features]
        outputs = [feature["output"] for feature in features]
        full_texts = [i + o for i, o in zip(inputs, outputs)]

        batch = self.tokenizer(
            full_texts,
            add_special_tokens=False,
            truncation=True,
            max_length=self.max_length,
            padding=True,
            return_tensors="pt",
        )

        # Build labels: mask input portion
        labels = batch["input_ids"].clone()
        labels[batch["attention_mask"] == 0] = -100

        for i, (inp, out) in enumerate(zip(inputs, outputs)):
            inp_ids = self.tokenizer(
                inp, add_special_tokens=False, truncation=False
            )["input_ids"]
            out_ids = self.tokenizer(
                out, add_special_tokens=False, truncation=False
            )["input_ids"]
            inp_len = len(inp_ids)
            out_len = len(out_ids)

            # Mask out the padding on the right side of labels
            seq_len = labels.shape[-1]
            # Find where the actual output ends (first pad token after input)
            # Set labels[:inp_len] to -100 (mask the input part)
            end = min(inp_len + out_len, seq_len)
            labels[i, :inp_len] = -100
            # If truncated, also mask the remaining
            if inp_len + out_len < seq_len:
                labels[i, inp_len + out_len:] = -100

        batch["labels"] = labels
        return batch

# ---------- checkpoint helpers ----------
def save_checkpoint(
    *,
    model: torch.nn.Module,
    tokenizer,
    output_dir: Path,
    global_step: int,
    round_name: str,
    epoch: int,
    final_round_save: bool = False,
) -> None:
    final_model_dir = output_dir / "final_model"
    target_model_dir = final_model_dir if final_round_save else output_dir / f"{global_step}"

    if is_main():
        target_model_dir.mkdir(parents=True, exist_ok=True)
        unwrapped = unwrap_model(model)
        unwrapped.save_pretrained(str(target_model_dir), safe_serialization=True)
        tokenizer.save_pretrained(str(target_model_dir))
        if not final_round_save:
            (target_model_dir / "trainer_state.json").write_text(
                json.dumps(
                    {
                        "global_step": global_step,
                        "round_name": round_name,
                        "epoch": epoch,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        if final_round_save:
            final_model_dir.mkdir(parents=True, exist_ok=True)
            unwrapped.save_pretrained(str(final_model_dir), safe_serialization=True)
            tokenizer.save_pretrained(str(final_model_dir))
    barrier()

def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def rotate_checkpoints(output_dir: Path, save_total_limit: int) -> None:
    if save_total_limit <= 0 or not is_main():
        return
    checkpoints = sorted(
        [path for path in output_dir.iterdir() if path.is_dir() and path.name.startswith("checkpoint-")],
        key=lambda path: int(path.name.split("-")[-1]),
    )
    for old in checkpoints[:-save_total_limit]:
        for child in sorted(old.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        old.rmdir()

# ---------- args ----------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True,
                        help="Path to CPT checkpoint to start from")
    parser.add_argument("--rounds-dir", type=Path, required=True,
                        help="Directory containing {round}_train.jsonl files")
    parser.add_argument("--rounds", nargs="+",
                        default=["train_S1", "train_S2", "train_S3",
                                 "train_Astar1", "train_Astar2", "train_Astar3"])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--num-train-epochs", type=int, default=1)
    parser.add_argument("--per-device-train-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=5e-5)
    parser.add_argument("--max-length", type=int, default=4096)
    parser.add_argument("--logging-steps", type=int, default=20)
    parser.add_argument("--save-steps", type=int, default=500)
    parser.add_argument("--save-total-limit", type=int, default=3)
    parser.add_argument("--dataloader-num-workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bf16", action="store_true", default=True)
    parser.add_argument("--no-bf16", dest="bf16", action="store_false")
    parser.add_argument("--gradient-checkpointing", action="store_true", default=True)
    parser.add_argument("--no-gradient-checkpointing", dest="gradient_checkpointing", action="store_false")
    parser.add_argument("--resume-from-global-step", type=int, default=0,
                        help="Global step to resume from (e.g., 28180). Will skip completed steps.")
    return parser.parse_args()

# ---------- main ----------
def main() -> None:
    args = parse_args()
    if "LOCAL_RANK" in os.environ:
        torch.cuda.set_device(int(os.environ["LOCAL_RANK"]))
    if int(os.environ.get("WORLD_SIZE", "1")) > 1 and not is_dist():
        dist.init_process_group(backend="nccl")

    set_seed(args.seed)
    device = torch.device("cuda", int(os.environ.get("LOCAL_RANK", "0"))) if torch.cuda.is_available() else torch.device("cpu")

    tokenizer = AutoTokenizer.from_pretrained(str(args.model), trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    model = AutoModelForCausalLM.from_pretrained(
        str(args.model),
        trust_remote_code=True,
        torch_dtype=torch.bfloat16 if args.bf16 else torch.float16,
    )
    model.config.use_cache = False
    if args.gradient_checkpointing:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        if hasattr(model, "enable_input_require_grads"):
            model.enable_input_require_grads()
    model.to(device)

    if is_dist():
        model = torch.nn.parallel.DistributedDataParallel(
            model,
            device_ids=[device.index],
            output_device=device.index,
            find_unused_parameters=False,
        )

    # Discover rounds
    round_specs = []
    total_update_steps = 0
    for round_name in args.rounds:
        dataset_path = args.rounds_dir / f"{round_name}.jsonl"
        if not dataset_path.is_file():
            raise FileNotFoundError(f"Missing dataset: {dataset_path}")
        raw_dataset = load_dataset("json", data_files=str(dataset_path), split="train")
        local_batches = math.ceil(len(raw_dataset) / (world_size() * args.per_device_train_batch_size))
        update_steps = math.ceil(local_batches / args.gradient_accumulation_steps) * args.num_train_epochs
        total_update_steps += update_steps
        round_specs.append((round_name, dataset_path, len(raw_dataset), update_steps))

    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        per_device_train_batch_size=args.per_device_train_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        weight_decay=0.01,
        bf16=args.bf16,
        fp16=not args.bf16,
        logging_steps=args.logging_steps,
        save_steps=args.save_steps,
        save_total_limit=args.save_total_limit,
        dataloader_num_workers=args.dataloader_num_workers,
        dataloader_pin_memory=True,
        report_to=["tensorboard"],
        run_name=str(args.output_dir),
        gradient_checkpointing=args.gradient_checkpointing,
        gradient_checkpointing_kwargs={"use_reentrant": False} if args.gradient_checkpointing else None,
        optim="adamw_torch_fused",
        seed=args.seed,
        data_seed=args.seed,
    )

    forbidden_name_patterns = [r"bias", r"layernorm", r"rmsnorm", r"(?:^|\.)norm(?:$|\.)", r"_norm(?:$|\.)"]
    decay_parameters = get_parameter_names(unwrap_model(model), [nn.LayerNorm], forbidden_name_patterns)
    optimizer_grouped_parameters = [
        {
            "params": [param for name, param in unwrap_model(model).named_parameters() if name in decay_parameters and param.requires_grad],
            "weight_decay": training_args.weight_decay,
        },
        {
            "params": [param for name, param in unwrap_model(model).named_parameters() if name not in decay_parameters and param.requires_grad],
            "weight_decay": 0.0,
        },
    ]
    optimizer = torch.optim.AdamW(
        optimizer_grouped_parameters,
        lr=args.learning_rate,
        betas=(training_args.adam_beta1, training_args.adam_beta2),
        eps=training_args.adam_epsilon,
        fused=torch.cuda.is_available(),
    )
    scheduler = get_scheduler(
        training_args.lr_scheduler_type,
        optimizer=optimizer,
        num_warmup_steps=training_args.get_warmup_steps(total_update_steps),
        num_training_steps=total_update_steps,
    )
    collator = SFTCollator(tokenizer, args.max_length)

    manifest = {
        "model": str(args.model),
        "rounds_dir": str(args.rounds_dir),
        "rounds": [
            {"name": name, "dataset": str(path), "dataset_rows": rows, "update_steps": steps}
            for name, path, rows, steps in round_specs
        ],
        "output_dir": str(args.output_dir),
        "total_update_steps": total_update_steps,
        "num_train_epochs": args.num_train_epochs,
        "per_device_train_batch_size": args.per_device_train_batch_size,
        "gradient_accumulation_steps": args.gradient_accumulation_steps,
        "learning_rate": args.learning_rate,
        "max_length": args.max_length,
        "bf16": args.bf16,
        "gradient_checkpointing": args.gradient_checkpointing,
        "world_size": world_size(),
        "continuous_without_reload": True,
        "loss_masking": "output_only",
    }
    if is_main():
        save_manifest(args.output_dir, manifest)
        print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
        print(f"Trainable parameters: {get_model_param_count(unwrap_model(model), trainable_only=True):,}", flush=True)
    barrier()

    global_step = args.resume_from_global_step
    start_time = time.time()
    cumulative_round_steps = {}
    running_total = 0
    for round_name, _, _, round_steps in round_specs:
        running_total += round_steps
        cumulative_round_steps[round_name] = running_total

    if args.resume_from_global_step > 0 and is_main():
        print(f"🔄 Resuming from global_step={args.resume_from_global_step}", flush=True)

    model.train()
    optimizer.zero_grad(set_to_none=True)

    for round_index, (round_name, dataset_path, dataset_rows, _) in enumerate(round_specs, start=1):
        raw_dataset = load_dataset("json", data_files=str(dataset_path), split="train")
        sampler = DistributedSampler(
            raw_dataset,
            num_replicas=world_size(),
            rank=rank(),
            shuffle=True,
            seed=args.seed + round_index - 1,
            drop_last=False,
        ) if is_dist() else None
        dataloader = DataLoader(
            raw_dataset,
            batch_size=args.per_device_train_batch_size,
            sampler=sampler,
            shuffle=sampler is None,
            collate_fn=collator,
            num_workers=args.dataloader_num_workers,
            pin_memory=True,
            drop_last=False,
        )
        local_batches = len(dataloader)
        if is_main():
            print(
                f"=== {round_name}: rows={dataset_rows}, local_batches={local_batches}, "
                f"epochs={args.num_train_epochs} ===",
                flush=True,
            )

        for epoch in range(args.num_train_epochs):
            if sampler is not None:
                sampler.set_epoch(epoch)
            running_loss = 0.0
            running_updates = 0
            data_wait_time = 0.0
            step_compute_time = 0.0
            iterator_started_at = time.time()
            for step, batch in enumerate(dataloader):
                batch_ready_at = time.time()
                data_wait_time += batch_ready_at - iterator_started_at
                batch = {key: value.to(device, non_blocking=True) for key, value in batch.items()}

                is_accum_step = (step + 1) % args.gradient_accumulation_steps == 0
                is_last_step = step + 1 == local_batches
                should_sync = is_accum_step or is_last_step
                sync_context = nullcontext()
                if is_dist() and hasattr(model, "no_sync") and not should_sync:
                    sync_context = model.no_sync()
                with sync_context:
                    outputs = model(**batch)
                    loss = outputs.loss / args.gradient_accumulation_steps
                    loss.backward()
                running_loss += loss.detach().float().item()

                if is_accum_step or is_last_step:
                    # Check if we should skip this step (already completed in previous run)
                    potential_next_step = global_step + 1
                    if potential_next_step <= args.resume_from_global_step:
                        # Skip this step - already completed
                        global_step = potential_next_step
                        continue

                    if training_args.max_grad_norm > 0:
                        torch.nn.utils.clip_grad_norm_(model.parameters(), training_args.max_grad_norm)
                    optimizer.step()
                    scheduler.step()
                    optimizer.zero_grad(set_to_none=True)
                    global_step += 1
                    running_updates += 1
                    step_compute_time += time.time() - batch_ready_at

                    if global_step == 1 or global_step % args.logging_steps == 0:
                        loss_tensor = torch.tensor(running_loss, device=device)
                        data_wait_tensor = torch.tensor(data_wait_time, device=device)
                        compute_tensor = torch.tensor(step_compute_time, device=device)
                        if is_dist():
                            dist.all_reduce(loss_tensor, op=dist.ReduceOp.AVG)
                            dist.all_reduce(data_wait_tensor, op=dist.ReduceOp.AVG)
                            dist.all_reduce(compute_tensor, op=dist.ReduceOp.AVG)
                        if is_main():
                            elapsed = time.time() - start_time
                            lr = scheduler.get_last_lr()[0]
                            avg_loss = loss_tensor.item() / max(running_updates, 1)
                            seconds_per_step = elapsed / max(global_step, 1)
                            total_eta_seconds = seconds_per_step * max(total_update_steps - global_step, 0)
                            round_eta_seconds = seconds_per_step * max(
                                cumulative_round_steps[round_name] - global_step,
                                0,
                            )
                            print(
                                json.dumps(
                                    {
                                        "round": round_name,
                                        "epoch": epoch + 1,
                                        "global_step": global_step,
                                        "total_steps": total_update_steps,
                                        "loss": avg_loss,
                                        "learning_rate": lr,
                                        "elapsed_seconds": round(elapsed, 2),
                                        "seconds_per_step": round(seconds_per_step, 4),
                                        "eta_seconds": round(total_eta_seconds, 2),
                                        "eta": format_duration(total_eta_seconds),
                                        "round_eta_seconds": round(round_eta_seconds, 2),
                                        "round_eta": format_duration(round_eta_seconds),
                                        "data_wait_seconds": round(data_wait_tensor.item(), 4),
                                        "compute_seconds": round(compute_tensor.item(), 4),
                                    },
                                    ensure_ascii=False,
                                ),
                                flush=True,
                            )
                        running_loss = 0.0
                        running_updates = 0.0
                        data_wait_time = 0.0
                        step_compute_time = 0.0

                    if args.save_steps > 0 and global_step % args.save_steps == 0:
                        round_output_dir = args.output_dir / round_name
                        save_checkpoint(
                            model=model,
                            tokenizer=tokenizer,
                            output_dir=round_output_dir,
                            global_step=global_step,
                            round_name=round_name,
                            epoch=epoch + 1,
                        )
                        rotate_checkpoints(round_output_dir, args.save_total_limit)
                iterator_started_at = time.time()

        round_output_dir = args.output_dir / round_name
        save_checkpoint(
            model=model,
            tokenizer=tokenizer,
            output_dir=round_output_dir,
            global_step=global_step,
            round_name=round_name,
            epoch=args.num_train_epochs,
            final_round_save=True,
        )
        if is_main():
            print(f"=== {round_name} finished: saved {round_output_dir / 'final_model'} ===", flush=True)

    if is_dist():
        dist.destroy_process_group()


if __name__ == "__main__":
    main()
