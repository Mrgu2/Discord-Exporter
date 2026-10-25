#!/usr/bin/env python3
import json
from urllib.request import ProxyHandler,Request,build_opener
from manage import command
value=command('status');p=build_opener(ProxyHandler({}));status=json.load(p.open(value['url']+'/api/status',timeout=10))
r=Request(value['url']+'/api/service',data=b'{"action":"restart"}',headers={'Content-Type':'application/json','X-Archive-Key':status['archive_key']},method='POST')
json.load(p.open(r,timeout=10));print('应用正在重启；原服务、资料和模型保留。')
