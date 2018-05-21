import pickle
from communication import ZmqClient
from core import Message, MessageType

client = ZmqClient(host='127.0.0.1', port='13480',
                   serializer=pickle.dumps, deserializer=pickle.loads)
msg = Message(MessageType.api_assign_job, {'context_name': 'default', 'context_folder': '.', 'pbrt_file': 'test.pbrt', 'max_workers': 1})
resp = client.request(msg)
print(resp.data)
msg = Message(MessageType.api_query_jobs, {})
resp = client.request(msg)
print(resp.data)
msg = Message(MessageType.api_query_workers, {})
resp = client.request(msg)
print(resp.data)
# msg = Message(MessageType.api_query_jobs, {})
