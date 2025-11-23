from app.agent_os import ag_os

if __name__ == "__main__":
    ag_os.serve(app="app.agent_os:app", host="localhost", port=7777, reload=True)
