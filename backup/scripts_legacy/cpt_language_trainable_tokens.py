#!/usr/bin/env python3
"""Launch language CPT with LoRA + trainable LM-MIDI token embeddings.

This reuses the Swift SFT/Pretrain pipeline but injects PEFT's
`trainable_token_indices` and `ensure_weight_tying` into LoraConfig so only
new LM-MIDI token rows are updated while preserving tied output behavior.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

from peft import LoraConfig

from swift.arguments import PretrainArguments
from swift.pipelines.train.pretrain import SwiftPretrain
from swift.pipelines.train.tuner import get_modules_to_save, get_target_modules
from swift.tuners import Swift
from swift.utils import get_logger


logger = get_logger()


def load_new_token_ids(base_tokenizer: Path, expanded_tokenizer: Path) -> List[int]:
    from transformers import AutoTokenizer

    base = AutoTokenizer.from_pretrained(str(base_tokenizer), trust_remote_code=True)
    expanded = AutoTokenizer.from_pretrained(str(expanded_tokenizer), trust_remote_code=True)
    base_vocab = set(base.get_vocab().keys())
    expanded_vocab = expanded.get_vocab()
    ids = sorted(expanded_vocab[token] for token in expanded_vocab if token not in base_vocab)
    if not ids:
        raise RuntimeError("No new tokens found between base tokenizer and expanded tokenizer")
    return ids


class SwiftPretrainTrainableTokens(SwiftPretrain):
    def prepare_model(self, args, model, *, template=None, train_dataset=None, task_type=None):
        if args.tuner_type != "lora":
            raise ValueError("This launcher currently expects tuner_type='lora'")
        if args.tuner_backend != "peft":
            raise ValueError("This launcher currently expects tuner_backend='peft'")

        task = (task_type or args.task_type).upper()
        if task == "EMBEDDING":
            peft_task = None
        elif task == "RERANKER":
            peft_task = "SEQ_CLS"
        elif task == "GENERATIVE_RERANKER":
            peft_task = "CAUSAL_LM"
        else:
            peft_task = task

        target_modules = get_target_modules(args, model)
        modules_to_save = get_modules_to_save(args, model, task)

        lora_kwargs = {
            "task_type": peft_task,
            "r": args.lora_rank,
            "target_modules": target_modules,
            "lora_alpha": args.lora_alpha,
            "lora_dropout": args.lora_dropout,
            "bias": args.lora_bias,
            "modules_to_save": modules_to_save,
            "use_rslora": args.use_rslora,
            "use_dora": args.use_dora,
            "lorap_lr_ratio": args.lorap_lr_ratio,
            "init_lora_weights": args.init_weights,
            "lora_dtype": args.lora_dtype,
            "trainable_token_indices": args.trainable_token_indices,
            "ensure_weight_tying": True,
        }
        if args.target_parameters is not None:
            lora_kwargs["target_parameters"] = args.target_parameters

        lora_config = LoraConfig(**lora_kwargs)
        model = Swift.prepare_model(model, lora_config)
        logger.info(f"lora_config: {lora_config}")
        return model


def build_args(parsed: argparse.Namespace, trainable_token_ids: List[int]) -> PretrainArguments:
    args = PretrainArguments(
        model=str(parsed.model),
        model_type="qwen3_5",
        dataset=[str(parsed.dataset)],
        output_dir=str(parsed.output_dir),
        template="qwen3_5",
        use_chat_template=False,
        loss_scale="all",
        torch_dtype="bfloat16",
        num_train_epochs=parsed.num_train_epochs,
        max_steps=parsed.max_steps,
        per_device_train_batch_size=parsed.per_device_train_batch_size,
        gradient_accumulation_steps=parsed.gradient_accumulation_steps,
        learning_rate=parsed.learning_rate,
        max_length=parsed.max_length,
        logging_steps=parsed.logging_steps,
        save_steps=parsed.save_steps,
        save_total_limit=parsed.save_total_limit,
        warmup_ratio=0.03,
        weight_decay=0.01,
        gradient_checkpointing=True,
        dataloader_num_workers=parsed.dataloader_num_workers,
        tuner_type="lora",
        tuner_backend="peft",
        lora_rank=parsed.lora_rank,
        lora_alpha=parsed.lora_alpha,
        lora_dropout=parsed.lora_dropout,
        target_modules=parsed.target_modules.split(","),
        report_to=["tensorboard"],
        logging_first_step=True,
        save_strategy="steps",
        train_dataloader_shuffle=True,
        remove_unused_columns=False,
        dataset_num_proc=1,
        use_hf=False,
        lazy_tokenize=True,
        seed=parsed.seed,
        data_seed=parsed.seed,
        save_only_model=False,
        trainable_parameters=[],
    )
    setattr(args, "trainable_token_indices", trainable_token_ids)
    return args


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
    parser.add_argument("--logging-steps", type=int, default=50)
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
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    trainable_token_ids = load_new_token_ids(args.base_tokenizer, args.expanded_tokenizer)
    train_args = build_args(args, trainable_token_ids)

    manifest = {
        "model": str(args.model),
        "dataset": str(args.dataset),
        "output_dir": str(args.output_dir),
        "new_trainable_token_count": len(trainable_token_ids),
        "new_trainable_token_min": min(trainable_token_ids),
        "new_trainable_token_max": max(trainable_token_ids),
        "save_steps": args.save_steps,
        "lora_rank": args.lora_rank,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "trainable_tokens_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info(json.dumps(manifest, ensure_ascii=False, indent=2))

    if args.dry_run:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return

    SwiftPretrainTrainableTokens(train_args).main()


if __name__ == "__main__":
    main()
