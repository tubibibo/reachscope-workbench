.class public Lcom/example/app/RegflowMove;
.super Ljava/lang/Object;
.source "RegflowMove.java"

# §6.1 规则 2：move-object vA, vB → 把 B 的标签复制给 A
.method public move(Landroid/content/Intent;)Ljava/lang/String;
    .locals 2

    invoke-virtual {p1}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    move-object v1, v0
    return-object v1
.end method
