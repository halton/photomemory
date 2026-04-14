import asyncio
import aiosqlite
from typing import Optional, Any, Callable, List, Tuple

# 全局异步数据库文件路径和连接池大小。默认池大小5，适合大多数API负载。
_async_db_path: Optional[str] = None
_async_pool_semaphore: Optional[asyncio.Semaphore] = None
_async_pool_size: int = 5

def set_async_db_path(path: str):
    """
    设置全局异步数据库文件路径。
    参数：
        path: 数据库文件路径
    """
    global _async_db_path
    _async_db_path = path

def set_async_pool_size(size: int):
    """
    设置异步连接池大小。需在事件循环内设置。
    参数：
        size: 最大并发数据库连接数
    """
    global _async_pool_size, _async_pool_semaphore
    _async_pool_size = size
    _async_pool_semaphore = asyncio.Semaphore(_async_pool_size)

async def _set_sqlite_pragmas(conn: aiosqlite.Connection):
    await conn.execute('PRAGMA journal_mode=WAL;')
    await conn.execute('PRAGMA synchronous=NORMAL;')
    await conn.execute('PRAGMA temp_store=MEMORY;')
    await conn.execute('PRAGMA cache_size=-20000;')
    await conn.execute('PRAGMA mmap_size=268435456;')

async def get_async_db() -> aiosqlite.Connection:
    """
    获取异步连接池中的数据库连接。
    用法：async with await get_async_db() as conn:
    返回：实现了异步上下文管理协议的连接对象。
    注意：每次调用都自动应用优化PRAGMA，出错自动释放。获取连接需 await。
    """
    global _async_db_path, _async_pool_semaphore
    if _async_db_path is None:
        raise RuntimeError("Async DB path not set. Call set_async_db_path(path) first.")
    if _async_pool_semaphore is None:
        _async_pool_semaphore = asyncio.Semaphore(_async_pool_size)
    await _async_pool_semaphore.acquire()
    try:
        conn = await aiosqlite.connect(_async_db_path)
        conn.row_factory = aiosqlite.Row
        await _set_sqlite_pragmas(conn)
        return _AsyncConnectionContext(conn, _async_pool_semaphore)
    except:
        _async_pool_semaphore.release()
        raise

async def close_pool():
    # Nothing to cleanup; placeholder for API compatibility
    pass

class _AsyncConnectionContext:
    """
    内部类：用于异步 with 管理 DB 连接与池资源。
    """
    def __init__(self, conn: aiosqlite.Connection, sem: asyncio.Semaphore):
        self._conn = conn
        self._sem = sem
    async def __aenter__(self):
        return self._conn
    async def __aexit__(self, exc_type, exc, tb):
        await self._conn.close()
        self._sem.release()

# Helper async query functions
def _asdict(row):
    return dict(row) if row is not None else None

async def fetch_one(query: str, params: Optional[Tuple]=None) -> Optional[dict]:
    """
    异步获取一行查询结果，返回dict。适合SELECT ... LIMIT 1。
    """
    async with await get_async_db() as conn:
        async with conn.execute(query, params or ()) as cursor:
            row = await cursor.fetchone()
            return _asdict(row)

async def fetch_all(query: str, params: Optional[Tuple]=None) -> List[dict]:
    """
    异步获取所有查询结果。每行dict，常用于SELECT列表。
    """
    async with await get_async_db() as conn:
        async with conn.execute(query, params or ()) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def execute(query: str, params: Optional[Tuple]=None) -> Any:
    """
    执行异步写操作（INSERT/UPDATE/DELETE等），返回 lastrowid。
    """
    async with await get_async_db() as conn:
        async with conn.execute(query, params or ()) as cursor:
            await conn.commit()
            return cursor.lastrowid
