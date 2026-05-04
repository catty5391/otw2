from collections.abc import Iterable

import openseespy.opensees as ops


class NodeReactionGetter:
    """Get node reactions by dof index after each analyze step.

    Typical usage:
    1. Run ``ops.analyze(1)`` for one step.
    2. Call ``getter.get_single(...)`` or ``getter.get_batch(...)``.

        Notes:
        - ``ops.reactions()`` is called by default before reading values to ensure
            current-step reactions are assembled.
        - ``dof`` should be an integer starting from 1.
    """

    def __init__(self, call_reactions_each_time=True):
        self.call_reactions_each_time = bool(call_reactions_each_time)

    @classmethod
    def _normalize_dof(cls, dof):
        if not isinstance(dof, int):
            raise TypeError("dof 必须是整数，例如 1,2,3...")
        if dof < 1:
            raise ValueError("dof 必须是正整数，且从 1 开始。")
        return dof

    def _prepare_reactions(self):
        if self.call_reactions_each_time:
            ops.reactions()

    def get_single(self, node_tag, dof):
        """Return reaction of one node in one direction at current step."""
        dof = self._normalize_dof(dof)
        self._prepare_reactions()
        return float(ops.nodeReaction(int(node_tag), dof))

    def get_batch(self, node_tags, dof):
        """Return reactions for multiple nodes in one direction.

        Returns a dict: ``{node_tag: reaction}``.
        """
        if not isinstance(node_tags, Iterable):
            raise TypeError("node_tags 必须是可迭代对象，如 list/tuple。")

        dof = self._normalize_dof(dof)
        self._prepare_reactions()

        result = {}
        for node_tag in node_tags:
            node_id = int(node_tag)
            result[node_id] = float(ops.nodeReaction(node_id, dof))
        return result


def get_node_reaction(node_tag, dof, call_reactions_each_time=True):
    """Convenience function for single-node reaction query."""
    getter = NodeReactionGetter(call_reactions_each_time=call_reactions_each_time)
    return getter.get_single(node_tag=node_tag, dof=dof)


def get_node_reactions(node_tags, dof, call_reactions_each_time=True):
    """Convenience function for batch node reaction query."""
    getter = NodeReactionGetter(call_reactions_each_time=call_reactions_each_time)
    return getter.get_batch(node_tags=node_tags, dof=dof)
