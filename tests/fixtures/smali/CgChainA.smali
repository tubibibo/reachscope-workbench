.class public Lcom/example/app/CgChainA;
.super Ljava/lang/Object;

.method public start()V
    .locals 1

    new-instance v0, Lcom/example/app/CgChainB;
    invoke-direct {v0}, Lcom/example/app/CgChainB;-><init>()V
    invoke-virtual {v0}, Lcom/example/app/CgChainB;->step()V
    return-void
.end method
