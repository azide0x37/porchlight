"""Opt-in loopback integration smoke; requires mosquitto and its clients.

Run with: uv run python tests/guest_mqtt_smoke.py
Uses isolated temporary config and never connects to household services.
"""
import http.client,json,os,socket,subprocess,sys,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
root=Path(__file__).resolve().parents[1]
def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));return s.getsockname()[1]
with tempfile.TemporaryDirectory() as tmp:
    tmp=Path(tmp); broker_port,web_port=port(),port()
    (tmp/'broker.conf').write_text(f'listener {broker_port} 127.0.0.1\nallow_anonymous true\npersistence false\n')
    cfg=tmp/'config';cfg.mkdir()
    local=json.loads((root/'etc/guest.json.example').read_text());local.update(enabled=True,access_token='smoke-'+'x'*40)
    (cfg/'guest.json').write_text(json.dumps(local));(cfg/'guest.json').chmod(0o600)
    (cfg/'porchlight.mqtt.env').write_text(f'HA_MQTT_ENABLE=1\nMQTT_HOST=127.0.0.1\nMQTT_PORT={broker_port}\nHA_BASE_TOPIC=smoke\n')
    env={**os.environ,'PORCHLIGHT_CONFIG_DIR':str(cfg),'PORCHLIGHT_STATE_DIR':str(tmp/'run'),'GUEST_WEB_PORT':str(web_port),'GUEST_MQTT_ALLOW_ANONYMOUS':'1'}
    broker=subprocess.Popen(['mosquitto','-c',str(tmp/'broker.conf')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    worker=None
    def request(path):
        c=http.client.HTTPConnection('127.0.0.1',web_port,timeout=2);c.request('GET',path,headers={'Authorization':'Bearer '+local['access_token']});r=c.getresponse();data=json.loads(r.read());c.close();return data
    def await_status(wanted,timeout=12):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            try:
                data=request('/api/guest/status')
                if data['status']==wanted:return data
            except (OSError,http.client.HTTPException):pass
            time.sleep(.15)
        raise AssertionError((wanted,data,worker.poll()))
    def publish(enabled=True,retain=False):
        msg={'schema_version':1,'enabled':enabled,'generated_at':datetime.now(timezone.utc).isoformat(),'session_id':'smoke-session','hvac':[]}
        subprocess.run(['mosquitto_pub','-h','127.0.0.1','-p',str(broker_port),'-t','smoke/guest/presentation','-s']+(['-r'] if retain else []),input=json.dumps(msg).encode(),check=True)
    try:
        time.sleep(.3)
        publish(retain=True)
        worker=subprocess.Popen([sys.executable,str(root/'src/porchlight-guest'),'--apply'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        await_status('unavailable');time.sleep(1)
        assert request('/api/guest/status')['status']=='unavailable'
        publish();await_status('starting');print('PASS retained snapshot rejected; live MQTT snapshot received',flush=True)
        publish(False);await_status('off');print('PASS OFF clears presentation via real MQTT',flush=True)
        broker.terminate();broker.wait();await_status('unavailable',12);print('PASS broker outage hides guest data',flush=True)
        broker=subprocess.Popen(['mosquitto','-c',str(tmp/'broker.conf')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        until=time.monotonic()+20
        while time.monotonic()<until:
            time.sleep(1);publish()
            if request('/api/guest/status')['status']=='starting':break
        else:raise AssertionError('reconnect failed')
        print('PASS broker reconnect accepts a fresh snapshot',flush=True)
        worker.terminate();worker.wait(timeout=12)
        assert worker.returncode==0,worker.stderr.read().decode()
        assert json.loads((tmp/'run/guest/status.json').read_text())['status']=='unavailable'
        print('PASS graceful shutdown records unavailable',flush=True)
    finally:
        if worker and worker.poll() is None:worker.kill();worker.wait()
        if broker.poll() is None:broker.terminate();broker.wait()
