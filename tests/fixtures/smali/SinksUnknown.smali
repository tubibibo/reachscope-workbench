.class public Lcom/example/app/SinkUnknownActivity;
.super Landroid/app/Activity;
.source "SinkUnknownActivity.java"

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/app/Activity;-><init>()V
    return-void
.end method

# 文件路径既没有私有目录信号也没有外部存储信号 → ownership=unknown（不默认 own）
.method public sinkUnknownFile()V
    .locals 2

    new-instance v0, Ljava/io/File;
    const-string v1, "/data/local/tmp/x.txt"
    invoke-direct {v0, v1}, Ljava/io/File;-><init>(Ljava/lang/String;)V

    return-void
.end method

# 跨组件但 Intent 不带数据 → ownership=unknown（不冒充 shared）
.method public sinkNoData()V
    .locals 1

    new-instance v0, Landroid/content/Intent;
    const-string v1, "com.example.app.PING"
    invoke-direct {v0, v1}, Landroid/content/Intent;-><init>(Ljava/lang/String;)V

    invoke-virtual {p0, v0}, Landroid/content/Context;->sendBroadcast(Landroid/content/Intent;)V

    return-void
.end method
