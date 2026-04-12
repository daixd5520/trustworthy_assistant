import asyncio
import hashlib
import hmac
import json
import time
from typing import Any, Callable, Optional
import httpx
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel


class WeComConfig(BaseModel):
    corp_id: str
    agent_id: str
    secret: str


class WeComMessage(BaseModel):
    ToUserName: str
    FromUserName: str
    CreateTime: int
    MsgType: str
    Content: Optional[str] = None
    MsgId: Optional[str] = None
    AgentID: Optional[int] = None


class WeComClient:
    def __init__(self, config: WeComConfig):
        self.config = config
        self.access_token: Optional[str] = None
        self.token_expires_at: float = 0
        self._http_client = httpx.AsyncClient(timeout=30.0)
    
    async def close(self):
        await self._http_client.aclose()
    
    async def _get_access_token(self) -> str:
        now = time.time()
        if self.access_token and now < self.token_expires_at - 60:
            return self.access_token
        
        url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        params = {
            "corpid": self.config.corp_id,
            "corpsecret": self.config.secret
        }
        
        response = await self._http_client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if data.get("errcode") != 0:
            raise Exception(f"Failed to get access token: {data}")
        
        self.access_token = data["access_token"]
        self.token_expires_at = now + data["expires_in"]
        return self.access_token
    
    async def send_text_message(self, to_user: str, content: str):
        token = await self._get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
        
        payload = {
            "touser": to_user,
            "msgtype": "text",
            "agentid": int(self.config.agent_id),
            "text": {
                "content": content
            }
        }
        
        response = await self._http_client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        
        if data.get("errcode") != 0:
            raise Exception(f"Failed to send message: {data}")
        
        return data
    
    @staticmethod
    def verify_signature(token: str, timestamp: str, nonce: str, signature: str) -> bool:
        arr = sorted([token, timestamp, nonce])
        tmp_str = "".join(arr).encode("utf-8")
        hash_str = hashlib.sha1(tmp_str).hexdigest()
        return hash_str == signature


def create_wecom_app(app_instance, on_message: Optional[Callable] = None) -> FastAPI:
    fastapi_app = FastAPI(title="Trustworthy Assistant WeCom Bot")
    wecom_client: Optional[WeComClient] = None
    
    @fastapi_app.on_event("startup")
    async def startup():
        nonlocal wecom_client
        config = app_instance.config
        if config.wecom_corp_id and config.wecom_agent_id and config.wecom_secret:
            wecom_config = WeComConfig(
                corp_id=config.wecom_corp_id,
                agent_id=config.wecom_agent_id,
                secret=config.wecom_secret
            )
            wecom_client = WeComClient(wecom_config)
    
    @fastapi_app.on_event("shutdown")
    async def shutdown():
        if wecom_client:
            await wecom_client.close()
    
    @fastapi_app.get("/wecom/webhook")
    async def wecom_verify(msg_signature: str, timestamp: str, nonce: str, echostr: str):
        token = app_instance.config.wecom_corp_id or ""
        if not WeComClient.verify_signature(token, timestamp, nonce, msg_signature):
            raise HTTPException(status_code=403, detail="Invalid signature")
        return int(echostr)
    
    @fastapi_app.post("/wecom/webhook")
    async def wecom_webhook(request: Request, background_tasks: BackgroundTasks,
                          msg_signature: str, timestamp: str, nonce: str):
        token = app_instance.config.wecom_corp_id or ""
        if not WeComClient.verify_signature(token, timestamp, nonce, msg_signature):
            raise HTTPException(status_code=403, detail="Invalid signature")
        
        body = await request.body()
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(body)
            msg_dict = {}
            for child in root:
                msg_dict[child.tag] = child.text
            
            message = WeComMessage(**msg_dict)
            
            if message.MsgType == "text" and message.Content:
                background_tasks.add_task(
                    process_wecom_message, 
                    app_instance, wecom_client, message
                )
            
        except Exception as e:
            print(f"Error processing WeCom message: {e}")
        
        return ""
    
    return fastapi_app


async def process_wecom_message(app_instance, wecom_client: Optional[WeComClient], message: WeComMessage):
    if not wecom_client or not message.Content:
        return
    
    try:
        agent = app_instance.agent_registry.default_agent_id
        agent_profile = app_instance.agent_registry.get(agent)
        
        result = app_instance.turn_processor.process_turn(
            message.Content,
            agent=agent_profile,
            channel="wecom",
            user_id=message.FromUserName
        )
        
        if result.assistant_text:
            await wecom_client.send_text_message(
                to_user=message.FromUserName,
                content=result.assistant_text
            )
        elif result.errors:
            await wecom_client.send_text_message(
                to_user=message.FromUserName,
                content=f"抱歉，处理出错了：{'; '.join(result.errors)}"
            )
    
    except Exception as e:
        print(f"Error in process_wecom_message: {e}")
        try:
            await wecom_client.send_text_message(
                to_user=message.FromUserName,
                content=f"抱歉，发生了错误：{str(e)}"
            )
        except:
            pass
