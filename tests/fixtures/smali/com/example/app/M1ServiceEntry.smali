.class public Lcom/example/app/M1ServiceEntry;
.super Landroid/app/Activity;
.source "M1ServiceEntry.java"

# M1 判别矩阵（源入口 D）：启动方法必须与目标组件类型一致。
# onCreate → startService(Intent(ctx, M1ServiceTarget)) + 可控 extra → 应建链
# onStart  → startActivity(Intent(ctx, M1ServiceTarget))              → 不应建链（类型不符）
# onResume → startService(Intent(ctx, CrossTarget))                   → 不应建链（类型不符）

.method public onCreate(Landroid/os/Bundle;)V
    .locals 5

    invoke-virtual {p0}, Lcom/example/app/M1ServiceEntry;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    const-string v1, "url"
    invoke-virtual {v0, v1}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v2

    new-instance v3, Landroid/content/Intent;
    const-class v4, Lcom/example/app/M1ServiceTarget;
    invoke-direct {v3, p0, v4}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    const-string v1, "cmd"
    invoke-virtual {v3, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v3}, Lcom/example/app/M1ServiceEntry;->startService(Landroid/content/Intent;)Landroid/content/ComponentName;
    return-void
.end method

.method public onStart()V
    .locals 5

    invoke-virtual {p0}, Lcom/example/app/M1ServiceEntry;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    const-string v1, "url"
    invoke-virtual {v0, v1}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v2

    new-instance v3, Landroid/content/Intent;
    const-class v4, Lcom/example/app/M1ServiceTarget;
    invoke-direct {v3, p0, v4}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    const-string v1, "cmd"
    invoke-virtual {v3, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v3}, Lcom/example/app/M1ServiceEntry;->startActivity(Landroid/content/Intent;)V
    return-void
.end method

.method public onResume()V
    .locals 5

    invoke-virtual {p0}, Lcom/example/app/M1ServiceEntry;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    const-string v1, "url"
    invoke-virtual {v0, v1}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v2

    new-instance v3, Landroid/content/Intent;
    const-class v4, Lcom/example/app/CrossTarget;
    invoke-direct {v3, p0, v4}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    invoke-virtual {v3, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v3}, Lcom/example/app/M1ServiceEntry;->startService(Landroid/content/Intent;)Landroid/content/ComponentName;
    return-void
.end method
