from langgraph.graph import StateGraph, END

from .state import SharedState
from .resume_agent import resume_analyzer_node
from .job_matcher_agent import job_matcher_node


def build_resume_graph():
    """
    Simple LangGraph pipeline:

    START -> resume_analyzer_node -> job_matcher_node -> END
    """
    graph = StateGraph(SharedState)

    # Nodes
    graph.add_node("resume_analyzer", resume_analyzer_node)
    graph.add_node("job_matcher", job_matcher_node)

    # Entry point
    graph.set_entry_point("resume_analyzer")

    # Edges
    graph.add_edge("resume_analyzer", "job_matcher")
    graph.add_edge("job_matcher", END)

    # Compile into a runnable graph
    return graph.compile()
