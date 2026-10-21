from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


def checkpoint_store(path):
    return AsyncSqliteSaver.from_conn_string(str(path))
