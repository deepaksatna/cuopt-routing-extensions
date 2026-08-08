import cudf
from cuopt.routing import DataModel, SolverSettings, Solve
ORDER_LOC = {0:1, 1:2, 2:3}
def build(with_prizes):
    cost=[[0 if i==j else 10 for j in range(4)] for i in range(4)]
    dm=DataModel(4,2,3)
    dm.add_cost_matrix(cudf.DataFrame(cost, dtype="float32"))
    dm.set_order_locations(cudf.Series([1,2,3], dtype="int32"))
    dm.add_capacity_dimension("units", cudf.Series([1,1,1], dtype="int32"), cudf.Series([1,1], dtype="int32"))
    dm.add_order_vehicle_match(0, cudf.Series([0], dtype="int32"))  # order 0 ONLY on vehicle 0
    if with_prizes:
        dm.set_order_prizes(cudf.Series([1.0,1.0,1.0], dtype="float32"))
    return dm
def analyze(tag, dm):
    s=SolverSettings(); s.set_time_limit(3)
    sol=Solve(dm,s)
    r=sol.get_route().to_pandas()
    served={}
    for i in range(r.shape[0]):
        if str(r["type"][i]) in ("Delivery","Pickup","Task"):
            loc=int(r["location"][i])
            for o,l in ORDER_LOC.items():
                if l==loc: served[o]=int(r["truck_id"][i])
    try: infeas=list(sol.get_infeasible_orders())
    except Exception as e: infeas="n/a"
    viol=[o for o,t in served.items() if o==0 and t!=0]
    vs = ("YES -> "+str(viol)) if viol else "no"
    print("["+tag+"] status="+str(sol.get_status())+"  served(order->truck)="+str(served)+"  infeasible_orders="+str(infeas))
    print("    order0 on FORBIDDEN vehicle? "+vs+"   | orders served: "+str(sorted(served))+" ("+str(len(served))+"/3)")
analyze("NO prizes", build(False))
analyze("WITH prizes=1", build(True))
