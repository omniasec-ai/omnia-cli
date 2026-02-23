I want to create a cli with python3 + TypeR that acts as  a command line client to  a remote app whose api is defined in the open_api.json file. The cli should be a chat like application that receives commands and sends them to the api server and prints the response. Use a beautiful terminal ui.

The cli should use dev containers for development, the api server is located at OMNIA_API_URL env variable and can be accessed using the OMNIA_API_TOKEN env variable (that token contains the BASIC or bearer string indicating its type).

Initially the cli should have the following commands, but we will add more later:

- /me: get current user details
- /agents: list all agent plugins available
- /agent agent_id: change to this agent by id or agent name
- /chats: list all chats in a beautiful table, with columns: id, name, last_message, last_message_date, unread_messages_count. Note that chats belongs to a project, usually a project has only one chat,so you will need to get all projects first.
- /chat <chat_id>: change to this chat
- /messages: list all messages in the current chat

When a user sends a message to the cli, it should be sent to the api server and the response should be printed in the cli. The cli should also print the response of the api server in the cli. A message entity should be created to store the interaction.

