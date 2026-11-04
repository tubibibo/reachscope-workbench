.class public Lcom/example/app/BridgeParamPath;
.super Ljava/lang/Object;
.source "BridgeParamPath.java"

# D-057：文件路径直接来自形参
# - read(String p1)       → 无目录信号 → cross-app（桥方法里 p1 是 JS 实参）
# - readCache(String p1)  → getCacheDir 信号 → own（信号优先）

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public read(Ljava/lang/String;)V
    .locals 2

    new-instance v0, Ljava/io/File;
    invoke-direct {v0, p1}, Ljava/io/File;-><init>(Ljava/lang/String;)V

    new-instance v1, Ljava/io/FileInputStream;
    invoke-direct {v1, v0}, Ljava/io/FileInputStream;-><init>(Ljava/io/File;)V

    return-void
.end method

.method public readCache(Ljava/lang/String;)V
    .locals 3

    invoke-virtual {p0}, Landroid/content/Context;->getCacheDir()Ljava/io/File;
    move-result-object v0

    new-instance v1, Ljava/io/File;
    invoke-direct {v1, v0, p1}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V

    new-instance v2, Ljava/io/FileInputStream;
    invoke-direct {v2, v1}, Ljava/io/FileInputStream;-><init>(Ljava/io/File;)V

    return-void
.end method
