#!/usr/bin/env python3
"""Run abcx2pm JSONL inference with vLLM and emit responses as JSONL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import torch
from transformers import AutoTokenizer
from vllm.model_executor.models.qwen3_5 import (
    Qwen3_5ForCausalLM,
    Qwen3_5ForConditionalGeneration,
    Qwen3_5MoeForCausalLM,
)
from vllm.model_executor.models import registry as vllm_registry

# vLLM 0.21.0 forgets to mark dense Qwen3.5 as hybrid, which prevents the
# mamba/attention block-size alignment path from running.
Qwen3_5ForCausalLM.is_hybrid = True
Qwen3_5MoeForCausalLM.is_hybrid = True
Qwen3_5ForCausalLM.get_mamba_state_shape_from_config = classmethod(
    Qwen3_5ForConditionalGeneration.get_mamba_state_shape_from_config.__func__
)
Qwen3_5ForCausalLM.get_mamba_state_dtype_from_config = classmethod(
    Qwen3_5ForConditionalGeneration.get_mamba_state_dtype_from_config.__func__
)
Qwen3_5ForCausalLM.get_mamba_state_copy_func = classmethod(
    Qwen3_5ForConditionalGeneration.get_mamba_state_copy_func.__func__
)
Qwen3_5MoeForCausalLM.get_mamba_state_shape_from_config = classmethod(
    Qwen3_5ForConditionalGeneration.get_mamba_state_shape_from_config.__func__
)
Qwen3_5MoeForCausalLM.get_mamba_state_dtype_from_config = classmethod(
    Qwen3_5ForConditionalGeneration.get_mamba_state_dtype_from_config.__func__
)
Qwen3_5MoeForCausalLM.get_mamba_state_copy_func = classmethod(
    Qwen3_5ForConditionalGeneration.get_mamba_state_copy_func.__func__
)


def _text_only_mrope_positions(self, input_tokens: list[int], mm_features: list[object]):
    del mm_features
    seq_len = len(input_tokens)
    positions = torch.arange(seq_len, dtype=torch.long)
    return positions.unsqueeze(0).repeat(3, 1), 0


Qwen3_5ForCausalLM.supports_mrope = True
Qwen3_5ForCausalLM.get_mrope_input_positions = _text_only_mrope_positions
Qwen3_5MoeForCausalLM.supports_mrope = True
Qwen3_5MoeForCausalLM.get_mrope_input_positions = _text_only_mrope_positions
vllm_registry.ModelRegistry.models["Qwen3_5ForCausalLM"] = vllm_registry._RegisteredModel.from_model_cls(
    Qwen3_5ForCausalLM
)
vllm_registry.ModelRegistry.models["Qwen3_5MoeForCausalLM"] = vllm_registry._RegisteredModel.from_model_cls(
    Qwen3_5MoeForCausalLM
)

from vllm import LLM, SamplingParams


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tensor-parallel-size", type=int, default=1)
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--max-model-len", type=int, default=1536)
    parser.add_argument("--block-size", type=int, default=0)
    parser.add_argument("--mamba-block-size", type=int, default=0)
    parser.add_argument("--mamba-cache-mode", default="none")
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.8)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--repetition-penalty", type=float, default=1.0)
    parser.add_argument("--max-tokens", type=int, default=1536)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--enable-prefix-caching", action="store_true")
    parser.add_argument("--enforce-eager", action="store_true")
    return parser.parse_args()


def load_training_template_name(model_path: Path) -> str | None:
    args_path = model_path / "args.json"
    if not args_path.exists():
        return None
    try:
        return json.loads(args_path.read_text(encoding="utf-8")).get("template")
    except Exception:
        return None


def render_qwen3_thinking_prompt(messages: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for message in messages:
        role = message["role"]
        content = message["content"]
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>\n")
    parts.append("<|im_start|>assistant\n")
    return "".join(parts)


def render_prompt(tokenizer: AutoTokenizer, template_name: str | None, messages: list[dict[str, str]]) -> str:
    # HF `apply_chat_template(..., enable_thinking=False)` appends an empty
    # `<think>\n\n</think>\n\n` block for Qwen3, which does not match the
    # ids Swift used during SFT for these non-thinking targets.
    chat_messages = [m for m in messages if m.get("role") in {"system", "user"}]
    if template_name == "qwen3_thinking":
        return render_qwen3_thinking_prompt(chat_messages)
    return tokenizer.apply_chat_template(
        chat_messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )


def load_prompts(
    path: Path,
    tokenizer: AutoTokenizer,
    template_name: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    prompts: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if not line.strip():
                continue
            record = json.loads(line)
            messages = record.get("messages")
            if not isinstance(messages, list) or not messages:
                raise ValueError(f"messages not found in row {idx}")
            prompts.append({"row": idx, "prompt": render_prompt(tokenizer, template_name, messages)})
            if limit > 0 and len(prompts) >= limit:
                break
    return prompts


def batched(items: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    if batch_size <= 0:
        raise ValueError(f"batch_size must be positive, got {batch_size}")
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def main() -> None:
    args = parse_args()
    tokenizer = AutoTokenizer.from_pretrained(str(args.model), trust_remote_code=True)
    template_name = load_training_template_name(args.model)
    prompts = load_prompts(args.input, tokenizer, template_name, args.limit)
    if not prompts:
        raise ValueError(f"no prompts found in {args.input}")

    llm_kwargs = {
        "model": str(args.model),
        "trust_remote_code": True,
        "tensor_parallel_size": args.tensor_parallel_size,
        "dtype": args.dtype,
        "max_model_len": args.max_model_len,
        "gpu_memory_utilization": args.gpu_memory_utilization,
        "enable_prefix_caching": args.enable_prefix_caching,
        "enforce_eager": args.enforce_eager,
        "disable_log_stats": True,
        "mamba_cache_mode": args.mamba_cache_mode,
    }
    if args.block_size > 0:
        llm_kwargs["block_size"] = args.block_size
    if args.mamba_block_size > 0:
        llm_kwargs["mamba_block_size"] = args.mamba_block_size

    llm = LLM(**llm_kwargs)
    sampling = SamplingParams(
        temperature=args.temperature,
        top_p=args.top_p,
        repetition_penalty=args.repetition_penalty,
        max_tokens=args.max_tokens,
        seed=args.seed,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    batches = batched(prompts, args.batch_size)
    preview = ""
    with args.output.open("w", encoding="utf-8") as f:
        for batch_index, batch in enumerate(batches, start=1):
            outputs = llm.generate(
                [item["prompt"] for item in batch],
                sampling_params=sampling,
                use_tqdm=True,
            )
            for item, output in zip(batch, outputs):
                text = output.outputs[0].text
                if not preview:
                    preview = text
                f.write(
                    json.dumps(
                        {
                            "row": item["row"],
                            "response": text,
                            "finish_reason": output.outputs[0].finish_reason,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            f.flush()
            print(f"batch {batch_index}/{len(batches)} done ({len(batch)} samples)")

    print(args.output)
    print(len(preview))
    print(preview[:400])


if __name__ == "__main__":
    main()
