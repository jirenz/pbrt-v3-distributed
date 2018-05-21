import pickle
from communication import ZmqClient
from core import Message, MessageType

def send_and_prin(client, msg):
    resp = client.request(msg)
    print(resp.data)

client = ZmqClient(host='127.0.0.1', port='13480',
                   serializer=pickle.dumps, deserializer=pickle.loads)
creation_di = {'context_name': 'default', 'context_folder': '.', 
               'pbrt_file': '/Users/jirenz/Dropbox/Courses Spring 17-18/CS348/project-repo/examples/test_scene/sphere.pbrt', 
               'max_workers': 1}
msg = Message(MessageType.api_assign_job, creation_di)
send_and_prin(client, msg)
msg = Message(MessageType.api_query_jobs, {})
send_and_prin(client, msg)
msg = Message(MessageType.api_query_workers, {})
send_and_prin(client, msg)
