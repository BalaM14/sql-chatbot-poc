from config import GROQ_API_KEY, MODEL_NAME
from groq import Groq
client = Groq(api_key=GROQ_API_KEY)

def groq_llm(system_prompt, user_prompt, temperature=0.1, max_tokens=500):
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )

    return response.choices[0].message.content.strip()