import opstool as opst
import matplotlib.pyplot as plt
sec_resp = opst.post.get_element_responses(odb_tag=1, ele_type="FiberSection")  # odb_tag=1 as above
print(sec_resp.data_vars)
print("-" * 100)
print(sec_resp.dims)
print("-" * 100)
print(sec_resp.coords)

defo = sec_resp["secDefo"].sel(eleTags=9, secPoints=4, DOFs="P")
fo = sec_resp["secForce"].sel(eleTags=9, secPoints=4, DOFs="P")

plt.plot(defo, fo)
plt.savefig("test.png")