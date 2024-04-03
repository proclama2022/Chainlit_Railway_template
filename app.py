import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List
from openai import AsyncOpenAI
from openai.types.beta import Thread
from openai.types.beta.thread_create_and_run_params import ThreadMessage
from openai.types.beta.threads import (
    TextContentBlock,
    ImageFileContentBlock
)
from openai.types.beta.threads.runs import RunStep
from openai.types.beta.threads.runs.tool_calls_step_details import ToolCall
from create_assistant import tool_map
from typing import Optional
from chainlit.element import Element
import chainlit as cl
from chainlit.server import app
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
import pyairtable
from urllib.parse import urlparse, parse_qs
import jwt
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


api_key = os.environ.get("OPENAI_API_KEY")
client = AsyncOpenAI(api_key=api_key)
assistant_id = os.environ.get("ASSISTANT_ID")

# List of allowed mime types
allowed_mime = ["text/csv", "application/pdf",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/json"]

API_KEY = 'patNGGF2SE0aMPe0q.9ffb4220c5a673c8784a715d274181447bd7c9689dc3297e7d842b956972ae8c'
BASE_ID = 'appFMt6Nbno4JDTUp'
TABLE_NAME = 'tblD6llM9pssdL7DH'

# Crea il client per Airtable
airtable_client = pyairtable.Api(API_KEY)


# Check if the files uploaded are allowed
async def check_files(files: List[Element]):
    for file in files:
        if file.mime not in allowed_mime:
            return False
    return True


# Upload files to the assistant
async def upload_files(files: List[Element]):
    file_ids = []
    for file in files:
        uploaded_file = await client.files.create(
            file=Path(file.path), purpose="assistants"
        )
        file_ids.append(uploaded_file.id)
    return file_ids


async def process_files(files: List[Element]):
    # Upload files if any and get file_ids
    file_ids = []
    if len(files) > 0:
        files_ok = await check_files(files)

        if not files_ok:
            file_error_msg = f"Hey, it seems you have uploaded one or more files that we do not support currently, please upload only : {(',').join(allowed_mime)}"
            await cl.Message(content=file_error_msg).send()
            return file_ids

        file_ids = await upload_files(files)

    return file_ids


async def process_thread_message(
    message_references: Dict[str, cl.Message], thread_message: ThreadMessage
):
    for idx, content_message in enumerate(thread_message.content):
        id = thread_message.id + str(idx)
        if isinstance(content_message, TextContentBlock):
            if id in message_references:
                msg = message_references[id]
                msg.content = content_message.text.value
                await msg.update()
            else:
                message_references[id] = cl.Message(
                    author="Sincrobank AI", content=content_message.text.value
                )
                await message_references[id].send()
        elif isinstance(content_message, ImageFileContentBlock):
            image_id = content_message.image_file.file_id
            response = await client.files.with_raw_response.content(image_id)
            elements = [
                cl.Image(
                    name=image_id,
                    content=response.content,
                    display="inline",
                    size="large",
                ),
            ]

            if id not in message_references:
                message_references[id] = cl.Message(
                    author="Sincrobank AI",
                    content="",
                    elements=elements,
                )
                await message_references[id].send()
        else:
            print("unknown message type", type(content_message))


async def process_tool_call(
    step_references: Dict[str, cl.Step],
    step: RunStep,
    tool_call: ToolCall,
    name: str,
    input: Any,
    output: Any,
    show_input: str = None,
):
    cl_step = None
    update = False
    if not tool_call.id in step_references:
        cl_step = cl.Step(
            name=name,
            type="tool",
            parent_id=cl.context.current_step.id,
            show_input=show_input,
        )
        step_references[tool_call.id] = cl_step
    else:
        update = True
        cl_step = step_references[tool_call.id]

    if step.created_at:
        cl_step.start = datetime.fromtimestamp(step.created_at).isoformat()
    if step.completed_at:
        cl_step.end = datetime.fromtimestamp(step.completed_at).isoformat()
    cl_step.input = input
    cl_step.output = output

    if update:
        await cl_step.update()
    else:
        await cl_step.send()


async def get_airtable_data(record):
    airtable_data = airtable_client.base(BASE_ID).table(TABLE_NAME).get(record)
    return airtable_data


async def add_user_message(record):
    user_data = await get_airtable_data(record)
    airtable_client.base(BASE_ID).table(TABLE_NAME).update(
        record, {'Messaggi utilizzati': user_data['fields']['Messaggi utilizzati'] + 1})
    print("Messaggio conteggiato correttamente!")
    return


class DictToObject:
    def __init__(self, dictionary):
        for key, value in dictionary.items():
            if isinstance(value, dict):
                setattr(self, key, DictToObject(value))
            else:
                setattr(self, key, value)

    def __str__(self):
        return "\n".join(f"{key}: {value}" for key, value in self.__dict__.items())


@cl.header_auth_callback
async def header_auth_callback(headers: Dict) -> Optional[cl.User]:
    # Verify the signature of a token in the header (ex: jwt token)
    # or check that the value is matching a row from your database
    referer_url = headers.get("referer")
    parsed_url = urlparse(referer_url)
    query_string = parsed_url.query
    # Estrazione del valore del parametro 'record' dalla query
    query_params = parse_qs(query_string)
    record_value = query_params.get('record', [None])[0]
    user_data = await get_airtable_data(record_value)

    if user_data:
        print(
            f"User {user_data['fields'].get('Name')} authenticated successfully!")
        return cl.User(identifier=user_data["fields"].get('Name'), metadata={"record": record_value})
    else:
        print("User not authenticated!")
        return None


@cl.on_chat_start
async def start_chat():
    files = []
    user = cl.user_session.get("user")
    airtable_data = await get_airtable_data(user.metadata.get("record"))
    remaining_messages = airtable_data["fields"].get("Messaggi rimanenti", 0)

    if remaining_messages > 0:
        await cl.Avatar(
            name="Sincrobank AI",
            path="public/logo_light.png",
        ).send()
        thread = await client.beta.threads.create()
        cl.user_session.set("messaggi_rimanenti", remaining_messages)
        cl.user_session.set("thread", thread)
        cl.user_session.set("files_ids", [])
        files_ids = cl.user_session.get("files_ids")
        await cl.Message(
            author="Sincrobank AI",
            content=f"Ciao {user.identifier}! Questo mese hai ancora {remaining_messages} messaggi disponibili."
        ).send()
        # Wait for the user to upload a file
        while not files:
            files = await cl.AskFileMessage(
                author="Sincrobank AI",
                content="Carica un Excel Sincrobank per iniziare!",
                accept=[
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
                disable_feedback=True,
            ).send()
        file_id = await upload_files(files)
        files_ids = files_ids + file_id
        cl.user_session.set("files_ids", files_ids)

        # Let the user know that the system is ready
        await cl.Message(
            content=f"`{files[0].name}` caricato correttamente. Chiedimi qualcosa!",
            author="Sincrobank AI",
        ).send()
    else:
        await cl.Message(
            author="Sincrobank AI",
            content=f"Ciao {user.identifier}! Hai esaurito i messaggi disponibili per questo mese. Effettua l'[upgrade](/upgrade) del tuo piano per continuare a usare Sincrobank AI."
        ).send()


@cl.step(name="Sincrobank AI", type="run", root=True)
async def run(thread_id: str, human_query: str, file_ids: List[str] = []):
    # Add the message to the thread
    init_message = await client.beta.threads.messages.create(
        thread_id=thread_id, role="user", content=human_query, file_ids=file_ids
    )

    # Create the run
    run = await client.beta.threads.runs.create(
        thread_id=thread_id, assistant_id=assistant_id
    )

    message_references = {}  # type: Dict[str, cl.Message]
    step_references = {}  # type: Dict[str, cl.Step]
    tool_outputs = []
    # Periodically check for updates
    while True:
        run = await client.beta.threads.runs.retrieve(
            thread_id=thread_id, run_id=run.id
        )

        # Fetch the run steps
        run_steps = await client.beta.threads.runs.steps.list(
            thread_id=thread_id, run_id=run.id, order="asc"
        )

        for step in run_steps.data:
            # Fetch step details
            run_step = await client.beta.threads.runs.steps.retrieve(
                thread_id=thread_id, run_id=run.id, step_id=step.id
            )
            step_details = run_step.step_details
            # Update step content in the Chainlit UI
            if step_details.type == "message_creation":
                thread_message = await client.beta.threads.messages.retrieve(
                    message_id=step_details.message_creation.message_id,
                    thread_id=thread_id,
                )
                await process_thread_message(message_references, thread_message)

            if step_details.type == "tool_calls":
                for tool_call in step_details.tool_calls:
                    if isinstance(tool_call, dict):
                        tool_call = DictToObject(tool_call)

                    if tool_call.type == "code_interpreter":
                        await process_tool_call(
                            step_references=step_references,
                            step=step,
                            tool_call=tool_call,
                            name=tool_call.type,
                            input=tool_call.code_interpreter.input
                            or "# Generating code",
                            output=tool_call.code_interpreter.outputs,
                            show_input="python",
                        )

                        tool_outputs.append(
                            {
                                "output": tool_call.code_interpreter.outputs or "",
                                "tool_call_id": tool_call.id,
                            }
                        )

                    elif tool_call.type == "retrieval":
                        await process_tool_call(
                            step_references=step_references,
                            step=step,
                            tool_call=tool_call,
                            name=tool_call.type,
                            input="Retrieving information",
                            output="Retrieved information",
                        )

                    elif tool_call.type == "function":
                        function_name = tool_call.function.name
                        function_args = json.loads(
                            tool_call.function.arguments)

                        function_output = tool_map[function_name](
                            **json.loads(tool_call.function.arguments)
                        )

                        await process_tool_call(
                            step_references=step_references,
                            step=step,
                            tool_call=tool_call,
                            name=function_name,
                            input=function_args,
                            output=function_output,
                            show_input="json",
                        )

                        tool_outputs.append(
                            {"output": function_output,
                                "tool_call_id": tool_call.id}
                        )
            if (
                run.status == "requires_action"
                and run.required_action.type == "submit_tool_outputs"
            ):
                await client.beta.threads.runs.submit_tool_outputs(
                    thread_id=thread_id,
                    run_id=run.id,
                    tool_outputs=tool_outputs,
                )

        await cl.sleep(2)  # Refresh every 2 seconds
        if run.status in ["cancelled", "failed", "completed", "expired"]:
            break


@cl.on_message
async def on_message(message_from_ui: cl.Message):
    thread = cl.user_session.get("thread")
    messaggi_rimanenti = cl.user_session.get("messaggi_rimanenti")
    if messaggi_rimanenti > 0:
        messaggi_rimanenti = messaggi_rimanenti - 1
        cl.user_session.set("messaggi_rimanenti", messaggi_rimanenti)
        await add_user_message(cl.user_session.get("user").metadata.get("record"))
        file_id = await process_files(message_from_ui.elements)
        files_ids = cl.user_session.get("files_ids")
        files_ids = files_ids + file_id
        cl.user_session.set("files_ids", files_ids)
        await run(
            thread_id=thread.id, human_query=message_from_ui.content, file_ids=files_ids
        )
    else:
        await cl.Message(
            author="Sincrobank AI",
            content="Hai esaurito i messaggi disponibili per questo mese. Effettua l'[upgrade](/upgrade) del tuo piano per continuare a usare Sincrobank AI."
        ).send()


@cl.on_chat_end
async def end_chat():
    files_ids = cl.user_session.get("files_ids")
    if files_ids:
        for file_id in files_ids:
            await client.files.delete(file_id)
            print(f"File {file_id} deleted")
    print("Chat ended", cl.user_session.get("id"))

# Lista dei domini autorizzati
origins = [
    "http://www.sincrobank.it",
    "https://www.sincrobank.it",
    "http://sincrobank.it",
    "https://sincrobank.it",
    "http://randy2783.preview.softr.app",
    "https://randy2783.preview.softr.app",]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Domini che possono fare richieste
    allow_credentials=True,  # Permette i cookie
    allow_methods=["*"],  # Permette tutti i metodi
    allow_headers=["*"],  # Permette tutti gli headers
)


@app.post("/token")
async def create_jwt(request: Request):
    data = await request.json()
    user = data.get('user')
    record = data.get('record')
    if user and record:
        to_encode = {
            "identifier": user,
            "metadata": {"record": record},
            "exp": datetime.now(ZoneInfo('UTC')) + timedelta(minutes=60)
        }
        encoded_jwt = jwt.encode(to_encode, os.environ.get(
            "CHAINLIT_AUTH_SECRET"), algorithm="HS256")
        print(f"Token creato correttamente! {encoded_jwt}")
        return encoded_jwt
    else:
        return "Errore nella creazione del token"
