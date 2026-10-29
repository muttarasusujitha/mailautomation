from fastapi import FastAPI, Request
app=FastAPI()
messages=[]
@app.post('/api/v1/email/send')
async def send(request:Request):
 messages.append(await request.json())
 return {'success':True}
@app.get('/messages')
async def get_messages(): return messages
@app.api_route('/{path:path}',methods=['GET','POST','DELETE','PATCH'])
async def business(path:str): return {'success':True,'path':path}
