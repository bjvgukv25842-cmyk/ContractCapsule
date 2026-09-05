# Locked Local Tokenizer Resource

This B-zone implementation resource is not part of any Capsule A-zone identity.
The o200k_base vocabulary is retrieved once during implementation from OpenAI's
public resource URL and verified against the SHA-256 embedded in the installed
official tiktoken 0.14.0 distribution (`tiktoken_ext/openai_public.py`). Runtime
compilation must read the packaged local resource and never fetch or repair it.

- Library: tiktoken 0.14.0, MIT, https://github.com/openai/tiktoken
- Vocabulary: https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken
- Expected SHA-256: 446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d
- API source: https://github.com/openai/tiktoken/blob/0.14.0/tiktoken/core.py
- Resource/profile source: https://github.com/openai/tiktoken/blob/0.14.0/tiktoken_ext/openai_public.py

This profile measures a neutral rendered text with explicit tokenizer binding.
It is not a claim about provider billing, hidden chat framing, or an inferred
mapping for an unverified model family. Those measurements remain separate.
