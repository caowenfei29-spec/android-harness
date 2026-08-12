#!/usr/bin/env python3
"""mobile_superagent CLI — submit a goal, watch it run to completion.

Usage:
    python cli.py --device-id <id> --goal "安装 YouTube 并验证打开"
    python cli.py --device-id <id> --goal "打开抖音浏览5个视频并摘要"
"""
import argparse
import sys
import time

import requests


def main():
    p = argparse.ArgumentParser(description="mobile_superagent CLI")
    p.add_argument("--goal", required=True, help="自然语言手机任务")
    p.add_argument("--device-id", required=True, help="设备 id（dev_xxx）")
    p.add_argument("--api", default="http://127.0.0.1:8000")
    p.add_argument("--skill-hint", default=None)
    args = p.parse_args()

    r = requests.post(f"{args.api}/api/tasks", json={
        "goal": args.goal, "device_id": args.device_id,
        "skill_hint": args.skill_hint})
    task = r.json()
    if "id" not in task:
        print("创建任务失败:", task)
        sys.exit(1)
    task_id = task["id"]
    print(f"任务已创建: {task_id}")

    while True:
        t = requests.get(f"{args.api}/api/tasks/{task_id}").json()
        status = t.get("status")
        print(f"  [{status}] 目标: {t.get('user_goal')}")
        if status in {"done", "failed", "cancelled"}:
            print("结果:", t.get("result_message"))
            break
        if status == "need_user":
            print("需要你处理:", t.get("need_user_reason"))
            print(t.get("need_user_instruction"))
            msg = input("完成后输入备注并回车继续: ")
            requests.post(f"{args.api}/api/tasks/{task_id}/continue",
                          json={"message": msg})
        time.sleep(2)


if __name__ == "__main__":
    main()
