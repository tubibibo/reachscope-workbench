.class public Lcom/example/app/CgChainB;
.super Ljava/lang/Object;

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public step()V
    .locals 1

    new-instance v0, Lcom/example/app/CgChainC;
    invoke-direct {v0}, Lcom/example/app/CgChainC;-><init>()V
    invoke-virtual {v0}, Lcom/example/app/CgChainC;->next()V
    return-void
.end method
