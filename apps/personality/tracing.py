"""Private report call snapshots. Never persist headers, keys or hidden reasoning."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
import json
import logging
import time

from django.db import DatabaseError
from django.utils import timezone

from .models import AnalysisCall,timestamp

scope=ContextVar('personality_report_call',default=None)
logger=logging.getLogger(__name__)


@contextmanager
def record_calls(assessment_id,job_id):
    token=scope.set((assessment_id,job_id))
    try:
        # Retain private diagnostic material for thirty days, including failures.
        AnalysisCall.objects.filter(created_at__lt=(timezone.now()-timedelta(days=30)).isoformat()).delete()
        yield
    finally:scope.reset(token)


def start(body,path,secret=''):
    owner=scope.get()
    if not owner or path!='/chat/completions' or not body:return None
    try:
        payload=json.loads(body['messages'][1]['content'])
        stage=payload.get('purpose','analysis')+(':'+payload['batch'] if isinstance(payload.get('batch'),str) else '')
        stored=json.loads(json.dumps(body,ensure_ascii=False).replace(secret,'[已隐藏密钥]')) if secret else body
        row=AnalysisCall.objects.create(assessment_id=owner[0],job_id=owner[1],stage=stage,request=stored)
        return row.pk,time.monotonic(),secret
    except (DatabaseError,ValueError,KeyError,TypeError):
        logger.warning('人格分析调用记录未能写入')


def finish(call,result=None,error=''):
    if not call:return
    safe={};status='error' if error else 'returned'
    if isinstance(result,dict):
        safe={key:result[key] for key in ['id','model','usage'] if key in result}
        choices=result.get('choices')
        safe['choices']=[]
        for choice in choices if isinstance(choices,list) else []:
            if not isinstance(choice,dict):continue
            message=choice.get('message') if isinstance(choice.get('message'),dict) else {}
            safe['choices'].append({'finish_reason':choice.get('finish_reason'),'message':{key:message.get(key) for key in ['role','content']}})
        if any(choice.get('finish_reason')=='length' for choice in safe['choices']):status='truncated'
    if call[2]:safe=json.loads(json.dumps(safe,ensure_ascii=False).replace(call[2],'[已隐藏密钥]'))
    try:
        AnalysisCall.objects.filter(pk=call[0]).update(status=status,response=safe,usage=safe.get('usage') if isinstance(safe.get('usage'),dict) else {},error=error[:300],elapsed_ms=max(0,int((time.monotonic()-call[1])*1000)),completed_at=timestamp())
    except DatabaseError:logger.warning('人格分析调用记录未能更新')
