# 0.0.6 

Improve performance of computation. Added multithread computation for LCA and Sobol.

Added method **sobol_simplify_model** that computed list of most meaningfull parameters, 
based on Sobol analysis, and generates simplified models based on it.

# 0.0.5
Add function `modelToExpr(model, impacts)`, returning expression with background activities replaced 
by the value of each impact.


# 0.0.4

* Added button for **exporting** data as csv on any **Dataframe** in stats tools
* **actToExpression** now replaces fixed params by their default values, providing simplified models.
* **newSwitchAct** can take custom amounts (not only '1') by providing tuple (act, amount)

# 0.0.3

First released version