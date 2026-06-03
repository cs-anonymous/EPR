#!/usr/bin/env python3
"""Train language CPT with Hugging Face Trainer + PEFT LoRA trainable tokens."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import List

import torch
from datasets import load_dataset
from peft import LoraConfig, TaskType, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments, TrainerCallback


def load_new_token_ids(base_tokenizer: Path, expanded_tokenizer: Path) -> List[int]:
    base = AutoTokenizer.from_pretrained(str(base_tokenizer), trust_remote_code=True)
    expanded = AutoTokenizer.from_pretrained(str(expanded_tokenizer), trust_remote_code=True)
    base_vocab = set(base.get_vocab().keys())
    expanded_vocab = expanded.get_vocab()
    ids = sorted(expanded_vocab[token] for token in expanded_vocab if token not in base_vocab)
    if not ids:
        raise RuntimeError("No new tokens found between base tokenizer and expanded tokenizer")
    return ids


class CausalLMTextCollator:
    def __init__(self, tokenizer, max_length: int):
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __call__(self, features):
        texts = [feature["text"] for feature in features]
        batch = self.tokenizer(
            texts,
            add_special_tokens=False,
            truncation=True,
            max_length=self.max_length,
            padding=True,
            return_tensors="pt",
        )
        labels = batch["input_ids"].clone()
        labels[batch["attention_mask"] == 0] = -100
        batch["labels"] = labels
        return batch


def build_model(args, trainable_token_ids: List[int]):
    model = AutoModelForCausalLM.from_pretrained(
        str(args.model),
        trust_remote_code=True,
        torch_dtype=torch.bfloat16 if args.bf16 else torch.float16,
        attn_implementation="flash_attention_2",  # 启用FlashAttention 2
    )
    model.config.use_cache = False

    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=args.lora_rank,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        target_modules=args.target_modules.split(","),
        trainable_token_indices=trainable_token_ids,
        ensure_weight_tying=True,
    )
    model = get_peft_model(model, lora_config)

    if args.gradient_checkpointing:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        if hasattr(model, "enable_input_require_grads"):
            model.enable_input_require_grads()

    return model, lora_config


def save_manifest(output_dir: Path, payload: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "train_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def to_jsonable(value):
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, set):
        return sorted(to_jsonable(v) for v in value)
    return value


class DetailedLoggingCallback(TrainerCallback):
    """Enhanced logging callback with detailed metrics similar to 0.8B training."""

    def __init__(self, total_steps: int, round_name: str = "train_S1"):
        self.total_steps = total_steps
        self.round_name = round_name
        self.start_time = None
        self.last_log_time = None

    def on_train_begin(self, args, state, control, **kwargs):
        self.start_time = time.time()
        self.last_log_time = self.start_time

    def on_log(self, args, state, control, logs=None, **kwargs):
        # Only log from main process (rank 0)
        if logs is None or state.global_step == 0:
            return

        if not state.is_world_process_zero:
            return

        current_time = time.time()
        elapsed_seconds = current_time - self.start_time

        # Calculate timing metrics
        seconds_per_step = elapsed_seconds / state.global_step if state.global_step > 0 else 0
        remaining_steps = self.total_steps - state.global_step
        eta_seconds = remaining_steps * seconds_per_step

        # Format ETA
        eta_hours = int(eta_seconds // 3600)
        eta_mins = int((eta_seconds % 3600) // 60)
        eta_secs = int(eta_seconds % 60)
        eta_str = f"{eta_hours:02d}:{eta_mins:02d}:{eta_secs:02d}"

        # Build detailed log
        detailed_log = {
            "round": self.round_name,
            "epoch": round(state.epoch, 4) if state.epoch else 0,
            "global_step": state.global_step,
            "total_steps": self.total_steps,
            "loss": round(logs.get("loss", 0.0), 6),
            "learning_rate": logs.get("learning_rate", 0.0),
            "elapsed_seconds": round(elapsed_seconds, 2),
            "seconds_per_step": round(seconds_per_step, 3),
            "eta_seconds": round(eta_seconds, 2),
            "eta": eta_str,
        }

        # Add grad_norm if available
        if "grad_norm" in logs:
            detailed_log["grad_norm"] = round(logs["grad_norm"], 4)

        # Print detailed JSON log
        print(json.dumps(detailed_log, ensure_ascii=False), flush=True)

        self.last_log_time = current_time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-tokenizer", type=Path, required=True)
    parser.add_argument("--expanded-tokenizer", type=Path, required=True)
    parser.add_argument("--num-train-epochs", type=float, default=1.0)
    parser.add_argument("--max-steps", type=int, default=-1)
    parser.add_argument("--per-device-train-batch-size", type=int, default=2)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--logging-steps", type=int, default=10)
    parser.add_argument("--save-steps", type=int, default=1000)
    parser.add_argument("--save-total-limit", type=int, default=3)
    parser.add_argument("--dataloader-num-workers", type=int, default=4)
    parser.add_argument("--lora-rank", type=int, default=32)
    parser.add_argument("--lora-alpha", type=int, default=64)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument(
        "--target-modules",
        type=str,
        default="q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bf16", action="store_true", default=True)
    parser.add_argument("--no-bf16", dest="bf16", action="store_false")
    parser.add_argument("--gradient-checkpointing", action="store_true", default=True)
    parser.add_argument("--no-gradient-checkpointing", dest="gradient_checkpointing", action="store_false")
    parser.add_argument("--resume-from-checkpoint", type=str, default=None, help="Path to checkpoint to resume from")
    args = parser.parse_args()

    trainable_token_ids = load_new_token_ids(args.base_tokenizer, args.expanded_tokenizer)
    tokenizer = AutoTokenizer.from_pretrained(str(args.expanded_tokenizer), trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    model, lora_config = build_model(args, trainable_token_ids)
    model.print_trainable_parameters()

    raw_dataset = load_dataset("json", data_files=str(args.dataset), split="train")
    collator = CausalLMTextCollator(tokenizer, args.max_length)

    # Calculate total training steps
    num_devices = torch.cuda.device_count() if torch.cuda.is_available() else 1
    effective_batch_size = args.per_device_train_batch_size * num_devices * args.gradient_accumulation_steps
    total_steps = len(raw_dataset) // effective_batch_size
    if args.max_steps > 0:
        total_steps = min(total_steps, args.max_steps)

    # Extract round name from output dir
    round_name = args.output_dir.name if hasattr(args.output_dir, 'name') else str(args.output_dir).split('/')[-1]

    manifest = {
        "model": str(args.model),
        "dataset": str(args.dataset),
        "output_dir": str(args.output_dir),
        "new_trainable_token_count": len(trainable_token_ids),
        "new_trainable_token_min": min(trainable_token_ids),
        "new_trainable_token_max": max(trainable_token_ids),
        "save_steps": args.save_steps,
        "lora_rank": args.lora_rank,
        "bf16": args.bf16,
        "gradient_checkpointing": args.gradient_checkpointing,
        "dataset_rows": len(raw_dataset),
        "lora_config": to_jsonable(lora_config.to_dict()),
    }
    save_manifest(args.output_dir, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)

    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        do_train=True,
        do_eval=False,
        num_train_epochs=args.num_train_epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.per_device_train_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        weight_decay=0.01,
        bf16=args.bf16,
        fp16=not args.bf16,
        logging_steps=args.logging_steps,
        logging_first_step=True,
        save_strategy="steps",
        save_steps=args.save_steps,
        save_total_limit=args.save_total_limit,
        save_only_model=True,
        dataloader_num_workers=args.dataloader_num_workers,
        dataloader_pin_memory=True,
        remove_unused_columns=False,
        report_to=[],  # Disable default logging to avoid duplicate short logs
        run_name=str(args.output_dir),
        gradient_checkpointing=args.gradient_checkpointing,
        gradient_checkpointing_kwargs={"use_reentrant": False} if args.gradient_checkpointing else None,
        optim="adamw_torch_fused",
        ddp_find_unused_parameters=False,
        seed=args.seed,
        data_seed=args.seed,
        disable_tqdm=False,  # Keep progress bar
        log_level="warning",  # Reduce log verbosity
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=raw_dataset,
        data_collator=collator,
        callbacks=[DetailedLoggingCallback(total_steps=total_steps, round_name=round_name)],
    )
    trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    trainer.save_model()
    # Don't save optimizer state - only save model


if __name__ == "__main__":
    main()
