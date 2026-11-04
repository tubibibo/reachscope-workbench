.class public Lcom/example/app/CgCycleA;
.super Ljava/lang/Object;

# A → B → A：环，BFS 必须能终止
.method public ping()V
    .locals 1

    invoke-static {}, Lcom/example/app/CgCycleB;->pong()V
    return-void
.end method
