from langgraph.graph import StateGraph, END

from .state import SharedState
from .interview_agent import generate_questions_node


def build_interview_graph():
    """
    Simple graph for generating questions:
    START -> generate_questions_node -> END
    """
    graph = StateGraph(SharedState)

    graph.add_node("generate_questions", generate_questions_node)
    graph.set_entry_point("generate_questions")
    graph.add_edge("generate_questions", END)

    return graph.compile()
