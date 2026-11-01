"""Terminal chat: `uv run python -m emporio.cli`."""
import uuid

from .graph import memory_graph, stream_turn


def main() -> None:
    graph = memory_graph()
    thread_id = uuid.uuid4().hex
    print("Empório da Música. Ctrl+C para sair.\n")
    while True:
        text = input("você> ").strip()
        if not text:
            continue
        for event in stream_turn(graph, thread_id, text):
            if event["type"] == "tool_start":
                print(f"  [{event['name']} {event['arguments']}]")
            elif event["type"] == "final":
                print(f"\ntéo> {event['text']}\n")


if __name__ == "__main__":
    main()
