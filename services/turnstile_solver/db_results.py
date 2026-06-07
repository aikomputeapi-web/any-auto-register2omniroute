import time
import asyncio

# In-memory database for temporary storage of verification code results
results_db = {}

async def init_db():
    print("[system] Result: The database was initialized successfully. (memory mode)")

async def save_result(task_id, task_type, data):
    # Store the result if data If it is a dictionary, it will be stored, otherwise a dictionary will be constructed.
    results_db[task_id] = data
    print(f"[system] Task {task_id} status update: {data.get('value', 'Processing')}")

async def load_result(task_id):
    return results_db.get(task_id)

async def cleanup_old_results(days_old=7):
    # Simple cleanup logic
    now = time.time()
    to_delete = []
    for tid, res in results_db.items():
        if isinstance(res, dict) and now - res.get('createTime', now) > days_old * 86400:
            to_delete.append(tid)
    for tid in to_delete:
        del results_db[tid]
    return len(to_delete)