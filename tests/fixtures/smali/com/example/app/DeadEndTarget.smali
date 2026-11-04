.class public Lcom/example/app/DeadEndTarget;
.super Landroid/app/Activity;
.source "DeadEndTarget.java"

# M1 反例目标：收到 Intent 但读完什么也不做（没有 sink）。
.method public onCreate(Landroid/os/Bundle;)V
    .locals 2

    invoke-virtual {p0}, Lcom/example/app/DeadEndTarget;->getIntent()Landroid/content/Intent;
    move-result-object v0
    const-string v1, "url"
    invoke-virtual {v0, v1}, Landroid/content/Intent;->getStringExtra(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v0
    return-void
.end method
