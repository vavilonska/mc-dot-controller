"""Exact diagnostic GET only, existing secret injected by operator; no retries/redirects."""
import http.client
import math
import socket
import threading
import time
from urllib.parse import urlsplit
from .schema import PATH,MAX_RESPONSE
from .strict import Invalid
from .watcher import Reply


class HttpTransport:
    def __init__(self,endpoint,token):
        try:p=urlsplit(endpoint);port=p.port
        except (ValueError,TypeError):raise Invalid('invalid loopback endpoint') from None
        if p.scheme!='http' or p.hostname not in ('127.0.0.1','::1') or not port or p.username or p.password or p.path not in ('','/') or p.query or p.fragment:raise Invalid('explicit HTTP loopback IP and port required')
        if not isinstance(token,str) or not token or len(token)>256 or any(ord(c)<33 or ord(c)>126 for c in token):raise Invalid('existing token required')
        self.host,self.port,self._token=p.hostname,port,token
    def get(self,path,*,timeout_s):
        if path!=PATH:raise Invalid('only exact diagnostic GET allowed')
        if type(timeout_s) not in (int,float) or not math.isfinite(timeout_s) or not 0<timeout_s<=.75:raise Invalid('bounded absolute timeout required')
        conn=http.client.HTTPConnection(self.host,self.port,timeout=timeout_s);received=bytearray();status=None;active=[None]
        deadline=time.monotonic()+timeout_s
        def abort():
            sock=active[0] or conn.sock
            if sock is not None:
                try:sock.shutdown(socket.SHUT_RDWR)
                except OSError:pass
                try:sock.close()
                except OSError:pass
        timer=threading.Timer(timeout_s,abort);timer.daemon=True;timer.start()
        def reply(complete,error=None):
            raw=bytes(received)
            if self._token.encode('ascii') in raw:return Reply(status,b'',False,'secret_quarantined')
            return Reply(status,raw,complete,error)
        try:
            conn.request('GET',PATH,headers={'Authorization':'Bearer '+self._token,'Connection':'close'})
            active[0]=conn.sock;response=conn.getresponse();status=response.status;expected=response.length
            while len(received)<=MAX_RESPONSE:
                remaining=deadline-time.monotonic()
                if remaining<=0:return reply(False,'timeout')
                if active[0] and active[0].fileno()!=-1:active[0].settimeout(remaining)
                chunk=response.read1(min(4096,MAX_RESPONSE+1-len(received)))
                if not chunk:
                    complete=time.monotonic()<deadline and (expected is None or len(received)==expected)
                    return reply(complete,None if complete else 'timeout' if time.monotonic()>=deadline else 'transport_exception')
                received.extend(chunk)
            return reply(False,'response_too_large')
        except ConnectionRefusedError:
            return reply(False,'connection_unavailable' if status is None and not received else 'transport_exception')
        except (TimeoutError,socket.timeout):return reply(False,'timeout')
        except (OSError,http.client.HTTPException):return reply(False,'timeout' if time.monotonic()>=deadline else 'transport_exception')
        finally:timer.cancel();conn.close()
