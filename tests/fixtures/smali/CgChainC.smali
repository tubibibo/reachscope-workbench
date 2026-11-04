.class public Lcom/example/app/CgChainC;
.super Ljava/lang/Object;

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public next()V
    .locals 1

    new-instance v0, Lcom/example/app/CgChainD;
    invoke-direct {v0}, Lcom/example/app/CgChainD;-><init>()V
    invoke-virtual {v0}, Lcom/example/app/CgChainD;->tail()V
    return-void
.end method
