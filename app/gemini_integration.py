# Commented out because this worked previously but at the time of writing there's package conflicts
# between google-generativeai and langchain. Ugh.

# import google.generativeai as genai
# from redis_tools import get_secrets_dict
# from utils import append_to_log

# def submit_prompt_to_gemini(prompt: str) -> str:
#     """Submits the prompt to Gemini 2.0 Flash and returns the response as a string."""
#     try:
#         api_secret_key = get_gemini_api_key()
#         client = genai.Client(api_key=api_secret_key)
#         response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
#         return response.text
#     except Exception as e:
#         append_to_log('flask_logs', 'GEMINI_INTEGRATION', 'ERROR', 'Exception thrown in submit_prompt_to_gemini: ' + repr(e))
#         return ''

import os
from langchain_google_genai import ChatGoogleGenerativeAI
from utils import get_secrets_dict
from utils import append_to_log
from typing import List
import signal
TIMEOUT = 6


def get_gemini_api_key() -> str:
    try:
        secrets_dict = get_secrets_dict()
        return secrets_dict['secrets']['gemini']['api_key']
    except Exception as e:
        append_to_log('ERROR', 'Exception thrown in get_gemini_api_key: ' + repr(e))
        return ''
    

def ensure_api_key_environment_variable() -> None:
    if "GOOGLE_API_KEY" not in os.environ or os.environ["GOOGLE_API_KEY"] == None or os.environ["GOOGLE_API_KEY"] == '':
        os.environ["GOOGLE_API_KEY"] = get_gemini_api_key()


def submit_prompt_to_gemini(prompt: str) -> str:
    ensure_api_key_environment_variable()

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
        max_tokens=None,
        timeout=None,
        max_retries=2
    )

    messages = [
        (
            "system",
            "You are a helpful assistant. Respond to the following query to the best of your ability.",
        ),
        (
            "user",
            prompt
        )
    ]
    
    append_to_log('INFO', 'The following prompt was submitted: ' + prompt)
    ai_msg = llm.invoke(messages)
    append_to_log('INFO', 'Gemini responsed: ' + ai_msg.content)
    return ai_msg.content


def submit_messages_to_gemini(messages: List) -> tuple:
    """Returns the text response as the first element and the messages list with the response appended as the second element."""
    try:     
        ensure_api_key_environment_variable()

        llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            temperature=0,
            max_tokens=None,
            timeout=5,
            max_retries=0
        )

        append_to_log('INFO', 'Submitting LangChain messages input to Gemini...')

        # This is ugly but I think the LangChain implementation for Gemini is bugged and it can hang forever
        signal.signal(signal.SIGALRM, handler) 
        signal.alarm(TIMEOUT) 

        ai_msg = llm.invoke(messages)
        append_to_log('INFO', 'Gemini responsed: ' + ai_msg.content)
        messages.append((
            "assistant",
            ai_msg.content
        ))
        return ai_msg.content, messages
    except Exception as e:
        append_to_log('ERROR', 'Exception thrown submitting messages to Gemini: ' + repr(e))
        error_message = "We're sorry, the AI model returned an error message. Please try again later."
        messages.append((
            "assistant",
            error_message
        ))
        return error_message, messages
    finally: 
            signal.alarm(0)  # Disable the alarm 


# Define a handler for the timeout 
def handler(signum, frame): 
    raise TimeoutError("Time limit exceeded!") 