"""各抓取源之间共享的发现结果（例如门户搜索里发现的抖音作品 ID，交给抖音源去抓评论）。"""
DISCOVERED = {"douyin": set(), "xiaohongshu": set()}
