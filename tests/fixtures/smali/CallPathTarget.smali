.class public Lcom/example/app/CallPathTarget;
.super Ljava/lang/Object;
.source "CallPathTarget.java"

# 被 CallPathEntry.onCreate 直接调用；方法名同样是入口方法名（`onCreate`），
# 所以 J5 的入口方法闸门放行 —— 这正是"深度 4 可达"要覆盖的形态。
.method public onCreate(Landroid/os/Bundle;)V
    .locals 2

    invoke-virtual {p0}, Lcom/example/app/CallPathTarget;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    invoke-virtual {v0}, Ljava/lang/Object;->toString()Ljava/lang/String;
    move-result-object v0
    invoke-virtual {p0, v0}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V
    return-void
.end method

.method public getIntent()Landroid/content/Intent;
    .locals 1

    const v0, 0x0
    return-object v0
.end method
