from fastapi import FastAPI, Response, status, Request
from typing import Callable, Awaitable
import socketio
import uvicorn
import uuid
import time
from utils import append_to_log, log_resource_access
from pymongo import MongoClient
from typing import List
import json
from pydantic import BaseModel
from transcripts import get_earnings_call_transcript
from gemini_integration import submit_messages_to_gemini
from fastapi.middleware.cors import CORSMiddleware

# This is fine because the Mongo port is not port forwarded
MONGO_CONNECTION_STRING = 'mongodb://admin:admin@192.168.0.121'

app = FastAPI()
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins="*")
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)

origins = ['*']

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def log_access(request: Request):
    try:
        url = 'https://ectai.cjremmett.com' + str(request.url.path)
        ip_address = request.client.host if request.client else "Unknown"
        log_resource_access(url, ip_address)
    except Exception as e:
        append_to_log('ERROR', f"Error logging resource access: {repr(e)}")
    
@app.middleware("http")
async def add_process_time_header(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    await log_access(request)
    response = await call_next(request)
    return response

### Heartbeat ###
@app.get("/")
async def heartbeat():
    return {"message": "FastAPI is alive!"}

### userid and chatid utilties ###
def generate_new_cjr_ai_id(type: str) -> str:
    """Generate a new user ID using UUID4."""
    new_uuid = f'cjr-{type}id-{str(uuid.uuid4())}'
    return new_uuid

@app.get("/get-new-ai-userid", status_code=200)
def get_new_ai_userid(response: Response):
    try:
        new_userid = generate_new_cjr_ai_id('user')
        append_to_log('INFO', 'New user created with ID ' + new_userid + '.')
        return ({"userid": new_userid})
    except Exception as e:
        append_to_log('ERROR', f"Error creating new user ID: {repr(e)}")
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return


### Database interactions ###
def store_earnings_call_inquiry_message_thread_to_database(userid: str, chatid: str, ticker: str, quarter: int, year: int, messages: List) -> bool:
    try:
        # Connect to MongoDB
        client = MongoClient(MONGO_CONNECTION_STRING)
        db = client["ai"]
        collection = db["chats"]

        # Generate the JSON to store
        messages_json = json.dumps(messages)

        # Upsert the message
        query = {"userid": userid, "chatid": chatid}
        update = {"$set": {
            "userid": userid,
            "chatid": chatid,
            "ticker": ticker,
            "quarter": quarter,
            "year": year,
            "timestamp": time.time(),
            "messages": messages_json
        }}
        result = collection.update_one(query, update, upsert=True)

        # Return True if the operation was successful
        return result.acknowledged

    except Exception as e:
        append_to_log('ERROR', f"Error upserting MongoDB record: {repr(e)}")
        return False

    finally:
        client.close()

def retrieve_earnings_call_inquiry_chat_from_database(chatid: str) -> dict:
    """
    Returns the messages as a list that can be submitted to LangChain or sent to the frontend.
    If the chat isn't found, returns None.
    """
    try:
        # Connect to MongoDB
        client = MongoClient(MONGO_CONNECTION_STRING)
        db = client["ai"]
        collection = db["chats"]

        query = {"chatid": chatid}
        first_record = collection.find_one(query)

        return first_record if first_record is not None else None

    except Exception as e:
        append_to_log('ERROR', f"Error retrieving MongoDB record: {repr(e)}")
        return None

    finally:
        client.close()

def get_messages_list_from_chat(chat: dict) -> List:
    """The messages value is stored as a string in MongoDB and we need to parse it into a list before passing to LangChain or the frontend."""
    return list(json.loads(chat['messages']))

def retrieve_earnings_call_inquiry_message_thread_from_database(chatid: str) -> List:
    chat = retrieve_earnings_call_inquiry_chat_from_database(chatid)
    return get_messages_list_from_chat(chat)

def get_chat_without_messages(chatid: str) -> List[dict]:
    """
    Retrieves the chat record from MongoDB where the chatid matches the given parameter.
    Doesn't include the messsages field to reduce resource usage.
    """
    try:
        # Connect to MongoDB
        client = MongoClient(MONGO_CONNECTION_STRING)
        db = client["ai"]
        collection = db["chats"]

        # Query the database and sort by timestamp in descending order
        query = {"chatid": chatid}
        projection = {"messages": 0, '_id': 0}
        chat = collection.find_one(query, projection)

        return chat

    except Exception as e:
        append_to_log('ERROR', f"Error retrieving chats from MongoDB: {repr(e)}")
        return []

    finally:
        client.close()

def get_all_chats_for_user(userid: str) -> List[dict]:
    """
    Retrieves all chat records from MongoDB where the userid matches the given parameter.
    Orders the results by timestamp in descending order.

    :param userid: The user ID to filter chats by.
    :return: A list of chat records as dictionaries, or an empty list if no records are found.
    """
    try:
        # Connect to MongoDB
        client = MongoClient(MONGO_CONNECTION_STRING)
        db = client["ai"]
        collection = db["chats"]

        # Query the database and sort by timestamp in descending order
        query = {"userid": userid}
        projection = {"messages": 0, '_id': 0}
        chats = list(collection.find(query, projection).sort("timestamp", -1))

        append_to_log('DEBUG', f"Chats retrieved for userid {userid}: {str(chats)}")

        return chats

    except Exception as e:
        append_to_log('ERROR', f"Error retrieving chats from MongoDB: {repr(e)}")
        return []

    finally:
        client.close()

@app.get("/get-earnings-call-chat-message-history", status_code=200)
def get_earnings_call_chat_message_history(chatid: str, response: Response):
    """
    Should be used by the front end to get the message history for a chat.
    Do not feed this into LangChain because it omits the first two system messages.
    """
    try:
        history = retrieve_earnings_call_inquiry_message_thread_from_database(chatid)
        # Omit the first two messages, which contain the transcript and the initial prompt.
        return (history[2:])

    except Exception as e:
        append_to_log('ERROR', f"Error retrieving chat history: {repr(e)}")
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return
    
@app.get("/get-earnings-call-chats-for-user", status_code=200)
def get_earnings_call_chats_for_user(userid: str, response: Response):
    try:
        chats = get_all_chats_for_user(userid)
        return chats

    except Exception as e:
        append_to_log('ERROR', f"Error retrieving chat history: {repr(e)}")
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return

### Create a new chat ###
class NewChat(BaseModel):
    userid: str
    ticker: str
    quarter: int
    year: int

@app.post("/start-new-chat", status_code=201)
def start_new_chat(new_chat: NewChat, response: Response):
    try:
        append_to_log('INFO', f'User requested to start earnings call transcript chat about ticker {new_chat.ticker} for Q{new_chat.quarter} {new_chat.year}.')

        # Get the transcript full text from API Ninjas third party service
        transcript = get_earnings_call_transcript(new_chat.ticker, new_chat.year, new_chat.quarter)

        # If API Ninjas couldn't return the transcript send a 400 response to the front end and don't create chat.
        # Reasons why this could happen:
        #   - API Ninjas doesn't have data for all companies. Try megacap tech companies since they usually have those.
        #   - User passed bad year or quarter (e.g. the company hasn't released earnings for that quarter yet).
        #   - Network failure, either on API Ninjas side or my flask service that pulls the transcripts was down.
        if transcript == None or len(transcript) < 10:
            append_to_log('INFO', f'Unable to retrieve earnings call transcript for ticker {new_chat.ticker} for Q{new_chat.quarter} {new_chat.year}.')
            response.status_code = status.HTTP_400_BAD_REQUEST
            return
        
        # Create the initial system messages
        messages_history = [(
            "system",
            transcript
        ),
        (
            "system",
            "Carefully review the entire earnings call transcript in the previous message before answering any questions. \
            Your response will be displayed verbatim to the user. Format it such that it will be easy and convenient for a human to read. \
            Carefully construct your response, ensuring it does not contain asterisks, bullet points or other formatting that a human would find difficult to read."
        ),
        (
            "assistant",
            f"I have retrieved the earnings call transcript for {new_chat.ticker} for Q{new_chat.quarter} {new_chat.year}. Feel free to ask me questions about it."
        )]

        # Generate a chat id for this chat
        chatid = generate_new_cjr_ai_id('chat')

        # Store the new chat in MongoDB
        if store_earnings_call_inquiry_message_thread_to_database(new_chat.userid, chatid, new_chat.ticker, new_chat.quarter, new_chat.year, messages_history):
            append_to_log('INFO', f'Successfully created earnings call transcript chat about ticker {new_chat.ticker} Q{new_chat.quarter} {new_chat.year} earnings.')
            # Return the chatid to the frontend. The frontend will then retrieve the contents of the chat via the chat history endpoint and switch to it.
            return {"chatid": chatid}
        else:
            append_to_log('ERROR', f'Failed to write out a new chat to MongoDB.')
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            return

    except Exception as e:
        append_to_log('ERROR', f"Error creating new chat: {repr(e)}")
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return

### Handle user message on an existing chat ###
def append_message_to_messages_list(role: str, message: str, messages: List) -> List:
    messages.append((role, message))
    return messages

async def send_earnings_call_inquiry_message_to_user(room: str, message: dict) -> None:
    # Need to use json.dumps to send a string because the frontend cannot parse a dict
    await sio.emit(room, json.dumps(message))

@sio.on("earnings_call_transcript_chat_message")
async def handle_earnings_call_transcript_chat_message(sid, data):
    """Expects data to contain JSON in the following format:
    {
        "chatid": "cjr-chatid-example",
        "message": "Sample message."
    }
    """
    ROOM = "earnings_call_transcript_chat_message"
    ERROR_STRING = "A technical problem prevented us from processing your message. Please notify cjremmett@gmail.com about this."
    append_to_log('TRACE', f"Received earnings call transcript chat message from userid {sid}. Their message is: {data}")

    # Get the chat history. Notify user of error if we couldn't retrieve it.
    chat = get_chat_without_messages(data['chatid'])
    if chat == None:
        await send_earnings_call_inquiry_message_to_user(ROOM, {'role': 'system', 'chatid': data['chatid'], 'message': ERROR_STRING})
        return
    messages_history = retrieve_earnings_call_inquiry_message_thread_from_database(data['chatid'])
    if messages_history == None or len(messages_history) < 3:
        await send_earnings_call_inquiry_message_to_user(ROOM, {'role': 'system', 'chatid': data['chatid'], 'message': ERROR_STRING})
        return
    
    # Append the user message to the list
    append_message_to_messages_list('user', data['message'], messages_history)

    # Send message back to user to load into the view
    await send_earnings_call_inquiry_message_to_user(ROOM, {'role': 'user', 'chatid': chat['chatid'], "message": data['message']})
    
    # Store updated message thread in database
    store_earnings_call_inquiry_message_thread_to_database(chat['userid'], chat['chatid'], chat['ticker'], chat['quarter'], chat['year'], messages_history)

    # Call the AI to get a response to the user message
    ai_response = submit_messages_to_gemini(messages_history)
    append_to_log('DEBUG', 'AI responded with: ' + ai_response[0])

    # Store updated message thread in database
    store_earnings_call_inquiry_message_thread_to_database(chat['userid'], chat['chatid'], chat['ticker'], chat['quarter'], chat['year'], messages_history)

    # Send AI response to the user
    await send_earnings_call_inquiry_message_to_user(ROOM, {'role': 'assistant', 'chatid': chat['chatid'], "message": ai_response[0]})

### Log SocketIO connections and disconnections ###
@sio.on("connect")
async def connect(sid, environ):
    append_to_log('TRACE', f"Client connected: {sid}")

@sio.on("disconnect")
async def disconnect(sid):
    append_to_log('TRACE', f"Client disconnected: {sid}")

if __name__ == "__main__":
    uvicorn.run(socket_app, host="0.0.0.0", port=3101)