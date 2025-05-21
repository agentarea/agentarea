from .code.populate_llm_providers import main as populate_llm_providers_main
from .code.minio_setup import minio_setup
from .code.infisical_setup import infisical_setup

def main():
    print("Hello from scripts!")
    print("Populating LLM providers and models...")
    populate_llm_providers_main()
    print("Minio setup...")
    minio_setup()
    print("Infisical setup...")
    infisical_setup()


if __name__ == "__main__":
    main()
