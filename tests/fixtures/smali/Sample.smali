.class public Lcom/example/app/Sample;
.super Ljava/lang/Object;
.source "Sample.java"

# interfaces
.implements Landroid/view/View$OnClickListener;

# instance fields
.field private mContext:Landroid/content/Context;


# virtual methods
.method public onClick(Landroid/view/View;)V
    .registers 2

    .line 12
    invoke-virtual {p1}, Landroid/view/View;->getContext()Landroid/content/Context;

    move-result-object v0 # trailing comment must be stripped

    .line 13
    invoke-virtual {v0}, Landroid/content/Context;->startActivity(Landroid/content/Intent;)V

    return-void
.end method


.method public static make(Ljava/lang/String;)Ljava/lang/String;
    .locals 1

    const-string v0, "https://example.com/#/page"

    .line 20
    invoke-virtual {v0, p0}, Ljava/lang/String;->concat(Ljava/lang/String;)Ljava/lang/String;

    move-result-object v0

    return-object v0
.end method
