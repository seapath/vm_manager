from flask import Flask
from flask_wtf.csrf import CSRFProtect
app = Flask(__name__)
csrf = CSRFProtect()
csrf.init_app(app)

import vm_manager as v

def execfunc(func,guest):
    try:
        out = func(guest)
    except Exception as err:
        return f"{err.__class__.__name__}: {err}",500
    if not out:
        out = "vm_manager did not return anything, should be OK"
    return out

@app.route('/')
def list_vms():
    return v.list_vms()

@app.route('/status/<guest>')
def status_vm(guest):
    return v.status(guest)

@app.route('/stop/<guest>')
def stop_vm(guest):
    out = execfunc(v.stop,guest)
    return out

@app.route('/start/<guest>')
def start_vm(guest):
    out = execfunc(v.start,guest)
    return out

if __name__ == "__main__":
    app.run(host='0.0.0.0')
