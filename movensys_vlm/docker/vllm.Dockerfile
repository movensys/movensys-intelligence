FROM nvcr.io/nvidia/vllm:26.04-py3

RUN pip install --no-cache-dir -U \
    "vllm==0.20.0" \
    "transformers>=5.6,<6,!=5.5.0" \
    "compressed-tensors>=0.15" \
    "huggingface_hub[cli]"

COPY vllm-entrypoint.sh /vllm-entrypoint.sh
RUN chmod +x /vllm-entrypoint.sh

ENTRYPOINT ["/vllm-entrypoint.sh"]
