.class public Lcom/example/app/CallPathEntry;
.super Ljava/lang/Object;
.source "CallPathEntry.java"

# D-062 的 fixture：sink 不在入口方法体内，而在深度 1 的 callee 里。
# 链上必须写清"入口 → callee"这一步，否则无法复核深度 ≤ 4。
.method public onCreate(Landroid/os/Bundle;)V
    .locals 1

    invoke-direct {p0, p1}, Lcom/example/app/CallPathTarget;->onCreate(Landroid/os/Bundle;)V
    return-void
.end method
