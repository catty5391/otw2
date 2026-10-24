// Experimental, single-process OpenSees adapter. Constitutive law stays in Python.
// Built against official OpenSees v3.8.0 headers; NOT a distributed/production plugin.
#include <Python.h>
#include <UniaxialMaterial.h>
#include <limits>

class Channel;
class FEM_ObjectBroker;
extern bool OPS_addUniaxialMaterial(UniaxialMaterial *);

class TMQPythonBridge : public UniaxialMaterial {
    PyObject *model;
    double value(const char *method) {
        PyGILState_STATE gil = PyGILState_Ensure();
        PyObject *result = PyObject_CallMethod(model, method, nullptr);
        double answer = result ? PyFloat_AsDouble(result) : std::numeric_limits<double>::quiet_NaN();
        Py_XDECREF(result);
        if (PyErr_Occurred()) { PyErr_Print(); answer = std::numeric_limits<double>::quiet_NaN(); }
        PyGILState_Release(gil);
        return answer;
    }
    int command(const char *method) {
        PyGILState_STATE gil = PyGILState_Ensure();
        PyObject *result = PyObject_CallMethod(model, method, nullptr);
        int answer = result ? (int)PyLong_AsLong(result) : -1;
        Py_XDECREF(result);
        if (PyErr_Occurred()) { PyErr_Print(); answer = -1; }
        PyGILState_Release(gil);
        return answer;
    }
public:
    TMQPythonBridge(int tag, PyObject *object) : UniaxialMaterial(tag, 991202), model(object) {
        PyGILState_STATE gil = PyGILState_Ensure(); Py_INCREF(model); PyGILState_Release(gil);
    }
    ~TMQPythonBridge() override {
        if (Py_IsInitialized()) {
            PyGILState_STATE gil = PyGILState_Ensure(); Py_DECREF(model); PyGILState_Release(gil);
        }
    }
    const char *getClassType() const override { return "TianMaQuPythonPrototype"; }
    int setTrialStrain(double strain, double rate = 0) override {
        PyGILState_STATE gil = PyGILState_Ensure();
        PyObject *result = PyObject_CallMethod(model, "set_trial_strain", "dd", strain, rate);
        int answer = result ? (int)PyLong_AsLong(result) : -1;
        Py_XDECREF(result);
        if (PyErr_Occurred()) { PyErr_Print(); answer = -1; }
        PyGILState_Release(gil);
        return answer;
    }
    double getStrain() override { return value("get_strain"); }
    double getStress() override { return value("get_stress"); }
    double getTangent() override { return value("get_tangent"); }
    double getInitialTangent() override { return value("get_initial_tangent"); }
    double getEnergy() override { return std::numeric_limits<double>::quiet_NaN(); } // unsupported, NOT zero dissipation
    int commitState() override { return command("commit_state"); }
    int revertToLastCommit() override { return command("revert_to_last_commit"); }
    int revertToStart() override { return command("revert_to_start"); }
    UniaxialMaterial *getCopy() override {
        PyGILState_STATE gil = PyGILState_Ensure();
        PyObject *copy = PyObject_CallMethod(model, "get_copy", nullptr);
        UniaxialMaterial *answer = copy ? new TMQPythonBridge(getTag(), copy) : nullptr;
        Py_XDECREF(copy);
        if (PyErr_Occurred()) PyErr_Print();
        PyGILState_Release(gil);
        return answer;
    }
    int sendSelf(int, Channel &) override { return -1; } // no MPI/database serialization
    int recvSelf(int, Channel &, FEM_ObjectBroker &) override { return -1; }
    void Print(OPS_Stream &stream, int = 0) override { stream << "TianMaQuPythonPrototype (experimental)"; }
};

extern "C" int tmq_register_python_material(int tag, PyObject *model) {
    auto *material = new TMQPythonBridge(tag, model);
    if (!OPS_addUniaxialMaterial(material)) { delete material; return -1; }
    return 0;
}
