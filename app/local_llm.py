import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import threading
import logging
from app.config import settings

logger = logging.getLogger(__name__)

class SimpleLocalLLM:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SimpleLocalLLM, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.model = None
        self.tokenizer = None
        self._initialized = True
        logger.info("SimpleLocalLLM initialized (model not yet loaded)")

    def _load_model(self):
        if self.model is not None:
            return

        logger.info(f"Loading model: {settings.LOCAL_THINKER_MODEL}")
        try:
            bnb_config = BitsAndBytesConfig(
                load_in_8bit=True,
                llm_int8_threshold=6.0,
                llm_int8_has_fp16_weight=False,
            )
            
            self.tokenizer = AutoTokenizer.from_pretrained(settings.LOCAL_THINKER_MODEL)
            self.model = AutoModelForCausalLM.from_pretrained(
                settings.LOCAL_THINKER_MODEL,
                quantization_config=bnb_config,
                device_map="auto",
                trust_remote_code=True
            )
            logger.info("Model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise

    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> str:
        self._load_model()
        
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        outputs = self.model.generate(
            **inputs,
            max_new_tokens=max_tokens,
            do_sample=True,
            temperature=temperature
        )
        # We only want the generated part, not the prompt
        input_length = inputs.input_ids.shape[1]
        generated_tokens = outputs[0][input_length:]
        return self.tokenizer.decode(generated_tokens, skip_special_tokens=True)

# Singleton access
simple_llm_service = SimpleLocalLLM()
