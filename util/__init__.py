from importlib import import_module

__all__ = [
	"CorrectedStoryDriftTracker",
	"ForceControl",
	"TagManager",
	"DriftPeakFinder",
	"PlotModel",
	"plot_model",
	"NodeReactionGetter",
	"get_node_reaction",
	"get_node_reactions",
]

_LAZY_IMPORTS = {
	"CorrectedStoryDriftTracker": ("processing.floor_drift", "CorrectedStoryDriftTracker"),
	"ForceControl": ("preprocess.force_control", "ForceControl"),
	"TagManager": ("preprocess.tag_manager", "TagManager"),
	"DriftPeakFinder": ("postprocess.drift_peak", "DriftPeakFinder"),
	"PlotModel": ("postprocess.plot_model", "PlotModel"),
	"plot_model": ("postprocess.plot_model", "plot_model"),
	"NodeReactionGetter": ("processing.node_reaction", "NodeReactionGetter"),
	"get_node_reaction": ("processing.node_reaction", "get_node_reaction"),
	"get_node_reactions": ("processing.node_reaction", "get_node_reactions"),
}


def __getattr__(name):
	if name not in _LAZY_IMPORTS:
		raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
	module_name, attr_name = _LAZY_IMPORTS[name]
	module = import_module(f".{module_name}", __name__)
	value = getattr(module, attr_name)
	globals()[name] = value
	return value
