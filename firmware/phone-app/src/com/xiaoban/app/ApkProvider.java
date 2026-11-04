package com.xiaoban.app;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;

import java.io.File;

/**
 * 极简 ContentProvider：只把 cache 目录下的 APK 暴露给系统安装器。
 * 用自带的，避免引入 AndroidX（我们的构建没有 Gradle 依赖管理）。
 */
public class ApkProvider extends ContentProvider {

    public static final String AUTHORITY = "com.xiaoban.app.apk";
    public static final String APK_NAME = "update.apk";

    public static File apkFile(android.content.Context ctx) {
        return new File(ctx.getCacheDir(), APK_NAME);
    }

    public static Uri apkUri() {
        return Uri.parse("content://" + AUTHORITY + "/" + APK_NAME);
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws java.io.FileNotFoundException {
        File f = apkFile(getContext());
        if (!f.exists()) throw new java.io.FileNotFoundException("没有 update.apk");
        return ParcelFileDescriptor.open(f, ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection,
                        String[] selectionArgs, String sortOrder) {
        File f = apkFile(getContext());
        String[] cols = projection != null ? projection
                : new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE};
        MatrixCursor c = new MatrixCursor(cols, 1);
        Object[] row = new Object[cols.length];
        for (int i = 0; i < cols.length; i++) {
            if (OpenableColumns.DISPLAY_NAME.equals(cols[i])) row[i] = APK_NAME;
            else if (OpenableColumns.SIZE.equals(cols[i])) row[i] = f.length();
            else row[i] = null;
        }
        c.addRow(row);
        return c;
    }

    @Override
    public String getType(Uri uri) {
        return "application/vnd.android.package-archive";
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        return null;
    }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) {
        return 0;
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) {
        return 0;
    }
}
