// SPDX-License-Identifier: GPL-2.0
//
// SUSFS (su hide file system) core - master config only.
// Sub-config features (SUS_PATH, SUS_MOUNT, SUS_KSTAT, ...) are added
// incrementally once CONFIG_KSU_SUSFS builds cleanly.

#include <linux/version.h>
#include <linux/cred.h>
#include <linux/fs.h>
#include <linux/slab.h>
#include <linux/seq_file.h>
#include <linux/printk.h>
#include <linux/namei.h>
#include <linux/list.h>
#include <linux/init_task.h>
#include <linux/mutex.h>
#include <linux/seqlock.h>
#include <linux/stat.h>
#include <linux/uaccess.h>
#include <linux/version.h>
#include <linux/fdtable.h>
#include <linux/statfs.h>
#include <linux/random.h>
#include <linux/kthread.h>
#include <linux/delay.h>
#include <linux/workqueue.h>
#include <linux/fsnotify_backend.h>
#include <linux/jump_label.h>
#include <linux/security.h>
#include <linux/bitmap.h>
#include <linux/limits.h>
#include <linux/rcupdate.h>
#include <linux/string.h>
#include <linux/susfs.h>

#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG
DEFINE_STATIC_KEY_TRUE(susfs_is_log_enabled);
#define SUSFS_LOGI(fmt, ...) if (static_branch_likely(&susfs_is_log_enabled)) pr_info("susfs:[%u][%d][%s] " fmt, current_uid().val, current->pid, __func__, ##__VA_ARGS__)
#define SUSFS_LOGE(fmt, ...) if (static_branch_likely(&susfs_is_log_enabled)) pr_err("susfs:[%u][%d][%s]" fmt, current_uid().val, current->pid, __func__, ##__VA_ARGS__)
#else
#define SUSFS_LOGI(fmt, ...)
#define SUSFS_LOGE(fmt, ...)
#endif

/* susfs_extra_works - deferred extra susfs work after do_umount in ksu_handle_setresuid() */
struct work_struct susfs_extra_works;
static void susfs_run_extra_works(struct work_struct *work)
{
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
	susfs_run_sus_path_loop();
#endif // #ifdef CONFIG_KSU_SUSFS_SUS_PATH
}

/* susfs_init */
void susfs_init(void)
{
	SUSFS_LOGI("Initializing susfs_extra_works\n");
	INIT_WORK(&susfs_extra_works, susfs_run_extra_works);
	SUSFS_LOGI("susfs is initialized! version: " SUSFS_VERSION " \n");
}

int susfs_show_variant(void __user **user_info)
{
	struct st_susfs_variant info = {0};

	if (copy_from_user(&info, (struct st_susfs_variant __user *)*user_info, sizeof(info)))
		return -EFAULT;

	strscpy(info.susfs_variant, SUSFS_VARIANT, SUSFS_MAX_VARIANT_BUFSIZE - 1);
	info.err = 0;
	if (copy_to_user((struct st_susfs_variant __user *)*user_info, &info, sizeof(info)))
		return -EFAULT;
	SUSFS_LOGI("CMD_SUSFS_SHOW_VARIANT -> ret: %d\n", info.err);
	return 0;
}

int susfs_show_version(void __user **user_info)
{
	struct st_susfs_version info = {0};

	if (copy_from_user(&info, (struct st_susfs_version __user *)*user_info, sizeof(info)))
		return -EFAULT;

	strscpy(info.susfs_version, SUSFS_VERSION, SUSFS_MAX_VERSION_BUFSIZE - 1);
	info.err = 0;
	if (copy_to_user((struct st_susfs_version __user *)*user_info, &info, sizeof(info)))
		return -EFAULT;
	SUSFS_LOGI("CMD_SUSFS_SHOW_VERSION -> ret: %d\n", info.err);
	return 0;
}

/* enable_log */
#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG
int susfs_enable_log(void __user **user_info)
{
	struct st_susfs_log info = {0};

	if (copy_from_user(&info, (struct st_susfs_log __user *)*user_info, sizeof(info)))
		return -EFAULT;

	if (info.enabled) {
		static_branch_enable(&susfs_is_log_enabled);
		pr_info("susfs: enable logging to kernel\n");
	} else {
		static_branch_disable(&susfs_is_log_enabled);
		pr_info("susfs: disable logging to kernel\n");
	}

	info.err = 0;
	if (copy_to_user(&((struct st_susfs_log __user *)*user_info)->err, &info.err, sizeof(info.err)))
		return -EFAULT;
	SUSFS_LOGI("CMD_SUSFS_ENABLE_LOG -> ret: %d\n", info.err);
	return 0;
}
#endif // #ifdef CONFIG_KSU_SUSFS_ENABLE_LOG

/* show_enabled_features */
#ifdef CONFIG_KSU_SUSFS_SHOW_ENABLED_FEATURES
static int copy_config_to_buf(const char *config_string, char *buf_ptr,
			      size_t *copied_size, size_t bufsize)
{
	size_t tmp_size = strlen(config_string);

	*copied_size += tmp_size;
	if (*copied_size >= bufsize) {
		SUSFS_LOGE("bufsize is not big enough to hold the string.\n");
		return -EINVAL;
	}
	memcpy(buf_ptr, config_string, tmp_size);
	return 0;
}

void susfs_get_enabled_features(void __user **user_info)
{
	struct st_susfs_enabled_features *info;
	char *buf_ptr;
	size_t copied_size = 0;
	int err = 0;

	info = kzalloc(sizeof(*info), GFP_KERNEL);
	if (!info) {
		err = -ENOMEM;
		if (copy_to_user(&((struct st_susfs_enabled_features __user *)*user_info)->err, &err, sizeof(err)))
			err = -EFAULT;
		SUSFS_LOGI("CMD_SUSFS_SHOW_ENABLED_FEATURES -> ret: %d\n", err);
		return;
	}

	if (copy_from_user(info, (struct st_susfs_enabled_features __user *)*user_info, sizeof(*info))) {
		info->err = -EFAULT;
		goto out_copy_to_user;
	}

	buf_ptr = info->enabled_features;

#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG
	info->err = copy_config_to_buf("CONFIG_KSU_SUSFS_ENABLE_LOG\n", buf_ptr,
				       &copied_size, SUSFS_ENABLED_FEATURES_SIZE);
	if (info->err)
		goto out_copy_to_user;
	buf_ptr = info->enabled_features + copied_size;
#endif // #ifdef CONFIG_KSU_SUSFS_ENABLE_LOG

	info->err = 0;
out_copy_to_user:
	if (copy_to_user((struct st_susfs_enabled_features __user *)*user_info, info, sizeof(*info))) {
		info->err = -EFAULT;
	}
	SUSFS_LOGI("CMD_SUSFS_SHOW_ENABLED_FEATURES -> ret: %d\n", info->err);
	kfree(info);
}
#endif // #ifdef CONFIG_KSU_SUSFS_SHOW_ENABLED_FEATURES
