.class public Lcom/example/app/CgUnresolved;
.super Ljava/lang/Object;

# invoke-virtual 到框架类（索引里没有）：target=None，且**不是** may_dispatch
# 这就是 §6.2 的“连不通”负例 —— 连不上不算错
.method public show(Landroid/view/View;)V
    .locals 1

    invoke-virtual {p1}, Landroid/view/View;->setVisibility(I)V
    return-void
.end method
