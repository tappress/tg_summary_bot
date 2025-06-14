from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.deepseek import DeepSeekProvider
from models import SearchQuery
from config import Config


config = Config()

# Create DeepSeek provider
deepseek_provider = DeepSeekProvider(api_key=config.deepseek_api_key)

# Create agent for generating search queries
search_query_agent = Agent(
    model=OpenAIModel(
        config.deepseek_model,
        provider=deepseek_provider
    ),
    result_type=SearchQuery,
    system_prompt=(
        "You are a search query generator for Telegram chats that may contain OCR-extracted text. "
        "Generate concise search queries (1-3 words) based on user questions. "
        "IMPORTANT: Consider that text may have OCR errors where similar characters get confused. "
        "For Ukrainian text, consider these common OCR mistakes: "
        "з/ц, и/і, а/о, н/п, е/є, р/p, у/y. "
        "If the user mentions 'резензія', also consider 'рецензія' (review). "
        "Focus on the core meaning and use the most likely correct spelling. "
        "Extract the main subject or keyword from the question."
    )
)


# Create agent for summarizing messages
summary_agent = Agent(
    model=OpenAIModel(
        config.deepseek_model,
        provider=deepseek_provider
    ),
    result_type=str,
    system_prompt=(
        "You are a message summarizer for Telegram chats. "
        "Answer the user's question based on the provided messages. "
        "IMPORTANT: Always respond in the same language as the user's question. "
        "If the question is in Ukrainian, respond in Ukrainian. "
        "If the question is in English, respond in English. "
        "Be concise and directly answer what was asked."
    )
)