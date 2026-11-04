.class public Lcom/example/app/TryCatch;
.super Ljava/lang/Object;
.source "TryCatch.java"

# instance fields
.field private value:Ljava/lang/String;


# direct methods
.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method


# virtual methods
# 全部是合法 smali：.catch / .catchall / .end packed-switch 都不得算未知语法（D-055）
.method public load(I)Ljava/lang/String;
    .locals 3

    :try_start_0
    invoke-direct {p0, p1}, Lcom/example/app/TryCatch;->pick(I)Ljava/lang/String;
    move-result-object v0
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :catch_0

    return-object v0

    :catch_0
    move-exception v0
    const-string v1, ""
    return-object v1
.end method

.method private pick(I)Ljava/lang/String;
    .locals 2

    packed-switch p1, :pswitch_data_0

    const-string v0, "other"
    return-object v0

    :pswitch_0
    const-string v0, "zero"
    return-object v0

    :pswitch_1
    const-string v0, "one"
    return-object v0

    :pswitch_data_0
    .packed-switch 0x0
        :pswitch_0
        :pswitch_1
    .end packed-switch
.end method

.method public copy()V
    .locals 2

    :try_start_1
    invoke-virtual {p0}, Lcom/example/app/TryCatch;->copy()V
    :try_end_1
    .catchall {:try_start_1 .. :try_end_1} :catchall_0

    return-void

    :catchall_0
    move-exception v0
    throw v0
.end method
