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
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
extern struct cred *ksu_cred;
static void susfs_run_sus_path_loop(void);
#endif

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

#ifdef CONFIG_KSU_SUSFS_SUS_PATH
	info->err = copy_config_to_buf("CONFIG_KSU_SUSFS_SUS_PATH\n", buf_ptr,
				       &copied_size, SUSFS_ENABLED_FEATURES_SIZE);
	if (info->err)
		goto out_copy_to_user;
	buf_ptr = info->enabled_features + copied_size;
#endif // #ifdef CONFIG_KSU_SUSFS_SUS_PATH

#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
	info->err = copy_config_to_buf("CONFIG_KSU_SUSFS_SUS_MOUNT\n", buf_ptr,
				       &copied_size, SUSFS_ENABLED_FEATURES_SIZE);
	if (info->err)
		goto out_copy_to_user;
	buf_ptr = info->enabled_features + copied_size;
#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MOUNT

#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
	info->err = copy_config_to_buf("CONFIG_KSU_SUSFS_SPOOF_UNAME\n", buf_ptr,
				       &copied_size, SUSFS_ENABLED_FEATURES_SIZE);
	if (info->err)
		goto out_copy_to_user;
	buf_ptr = info->enabled_features + copied_size;
#endif // #ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME

	info->err = 0;
out_copy_to_user:
	if (copy_to_user((struct st_susfs_enabled_features __user *)*user_info, info, sizeof(*info))) {
		info->err = -EFAULT;
	}
	SUSFS_LOGI("CMD_SUSFS_SHOW_ENABLED_FEATURES -> ret: %d\n", info->err);
	kfree(info);
}
#endif // #ifdef CONFIG_KSU_SUSFS_SHOW_ENABLED_FEATURES

/* sus_path */
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
DEFINE_STATIC_SRCU(susfs_srcu_sus_path_loop);
static DEFINE_MUTEX(susfs_mutex_lock_sus_path);
static LIST_HEAD(LH_SUS_PATH_LOOP);
const struct qstr susfs_fake_qstr_name = QSTR_INIT("..5.u.S", 7);

void susfs_add_sus_path(void __user **user_info)
{
	struct st_susfs_sus_path info = {0};
	struct path path;
	struct inode *inode = NULL;

	if (copy_from_user(&info, (struct st_susfs_sus_path __user *)*user_info, sizeof(info))) {
		info.err = -EFAULT;
		goto out_copy_to_user;
	}

	info.err = kern_path(info.target_pathname, LOOKUP_FOLLOW, &path);
	if (info.err) {
		SUSFS_LOGE("failed opening file '%s'\n", info.target_pathname);
		goto out_copy_to_user;
	}

	inode = d_backing_inode(path.dentry);
	if (!inode || !inode->i_mapping) {
		SUSFS_LOGE("inode || inode->i_mapping is NULL\n");
		info.err = -ENOENT;
		goto out_path_put_path;
	}

	set_bit(AS_FLAGS_SUS_PATH, &inode->i_mapping->flags);
	SUSFS_LOGI("flagged AS_FLAGS_SUS_PATH on pathname: '%s', ino: '%lu', inode->i_mapping->flags: 0x%lx\n",
			info.target_pathname, inode->i_ino, inode->i_mapping->flags);
	info.err = 0;
out_path_put_path:
	path_put(&path);
out_copy_to_user:
	if (copy_to_user(&((struct st_susfs_sus_path __user *)*user_info)->err, &info.err, sizeof(info.err))) {
		info.err = -EFAULT;
	}
	SUSFS_LOGI("CMD_SUSFS_ADD_SUS_PATH -> ret: %d\n", info.err);
}

void susfs_add_sus_path_loop(void __user **user_info)
{
	struct st_susfs_sus_path_list *new_list = NULL;
	struct st_susfs_sus_path info = {0};

	if (copy_from_user(&info, (struct st_susfs_sus_path __user *)*user_info, sizeof(info))) {
		info.err = -EFAULT;
		goto out_copy_to_user;
	}

	if (*info.target_pathname == '\0') {
		SUSFS_LOGE("target_pathname cannot be empty\n");
		info.err = -EINVAL;
		goto out_copy_to_user;
	}

	new_list = kzalloc(sizeof(struct st_susfs_sus_path_list), GFP_KERNEL);
	if (!new_list) {
		info.err = -ENOMEM;
		goto out_copy_to_user;
	}
	strscpy(new_list->info.target_pathname, info.target_pathname, SUSFS_MAX_LEN_PATHNAME - 1);
	strscpy(new_list->target_pathname, info.target_pathname, SUSFS_MAX_LEN_PATHNAME - 1);
	INIT_LIST_HEAD(&new_list->list);
	mutex_lock(&susfs_mutex_lock_sus_path);
	list_add_tail_rcu(&new_list->list, &LH_SUS_PATH_LOOP);
	mutex_unlock(&susfs_mutex_lock_sus_path);
	SUSFS_LOGI("target_pathname: '%s', is successfully added to LH_SUS_PATH_LOOP\n", new_list->target_pathname);
	info.err = 0;
out_copy_to_user:
	if (copy_to_user(&((struct st_susfs_sus_path __user *)*user_info)->err, &info.err, sizeof(info.err))) {
		info.err = -EFAULT;
	}
	SUSFS_LOGI("CMD_SUSFS_ADD_SUS_PATH_LOOP -> ret: %d\n", info.err);
}

static void susfs_run_sus_path_loop(void)
{
	struct st_susfs_sus_path_list *cursor = NULL;
	struct path path;
	struct inode *inode;
	const struct cred *saved = override_creds(ksu_cred);
	int srcu_idx = srcu_read_lock(&susfs_srcu_sus_path_loop);

	list_for_each_entry_rcu(cursor, &LH_SUS_PATH_LOOP, list) {
		if (!kern_path(cursor->target_pathname, 0, &path)) {
			inode = d_backing_inode(path.dentry);
			if (inode && inode->i_mapping) {
				set_bit(AS_FLAGS_SUS_PATH, &inode->i_mapping->flags);
				SUSFS_LOGI("re-flag AS_FLAGS_SUS_PATH on path '%s', inode->i_ino: '%lu', inode->i_mapping->flags: 0x%lx\n",
						cursor->target_pathname, inode->i_ino, inode->i_mapping->flags);
			}
			path_put(&path);
		}
	}
	srcu_read_unlock(&susfs_srcu_sus_path_loop, srcu_idx);
	revert_creds(saved);
}

static inline bool is_i_uid_not_allowed(uid_t i_uid) {
	return likely(current_uid().val != i_uid);
}

bool susfs_is_inode_sus_path(struct inode *inode)
{
	if (!susfs_is_current_proc_umounted_app()) {
		return false;
	}
	if (!inode->i_mapping) {
		SUSFS_LOGE("inode->i_mapping is NULL\n");
		return false;
	}
	if (unlikely(test_bit(AS_FLAGS_SUS_PATH, &inode->i_mapping->flags) &&
		     is_i_uid_not_allowed(inode->i_uid.val))) {
		SUSFS_LOGI("hiding path with ino '%lu'\n", inode->i_ino);
		return true;
	}
	return false;
}
#endif // #ifdef CONFIG_KSU_SUSFS_SUS_PATH

/* sus_mount */
#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
DEFINE_STATIC_KEY_TRUE(susfs_is_sdcard_android_data_not_decrypted);
DEFINE_STATIC_KEY_FALSE(susfs_is_hide_sus_mnts_for_non_su_procs_enabled);

void susfs_set_hide_sus_mnts_for_non_su_procs(void __user **user_info)
{
	struct st_susfs_hide_sus_mnts_for_non_su_procs info = {0};

	if (copy_from_user(&info, (struct st_susfs_hide_sus_mnts_for_non_su_procs __user *)*user_info, sizeof(info))) {
		info.err = -EFAULT;
		goto out_copy_to_user;
	}

	if (info.enabled) {
		static_branch_enable(&susfs_is_hide_sus_mnts_for_non_su_procs_enabled);
	} else {
		static_branch_disable(&susfs_is_hide_sus_mnts_for_non_su_procs_enabled);
	}

	SUSFS_LOGI("susfs_is_hide_sus_mnts_for_non_su_procs_enabled: %d\n", static_key_enabled(&susfs_is_hide_sus_mnts_for_non_su_procs_enabled));
	info.err = 0;
out_copy_to_user:
	if (copy_to_user(&((struct st_susfs_hide_sus_mnts_for_non_su_procs __user *)*user_info)->err, &info.err, sizeof(info.err))) {
		info.err = -EFAULT;
	}
	SUSFS_LOGI("CMD_SUSFS_HIDE_SUS_MNTS_FOR_NON_SU_PROCS -> ret: %d\n", info.err);
}
#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MOUNT

/* deprecated: add_sus_mount - kernel auto-detects ksu-domain mounts */
#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
void susfs_add_sus_mount(void __user **user_info)
{
	struct st_susfs_sus_mount info = {0};

	if (copy_from_user(&info, (struct st_susfs_sus_mount __user *)*user_info, sizeof(info))) {
		info.err = -EFAULT;
		goto out_copy_to_user;
	}

	info.err = 0;
out_copy_to_user:
	if (copy_to_user(&((struct st_susfs_sus_mount __user *)*user_info)->err, &info.err, sizeof(info.err))) {
		info.err = -EFAULT;
	}
	SUSFS_LOGI("set SUS_MOUNT on pathname: '%s', dev: '%lu' -> ret: %d\n",
			info.target_pathname, info.target_dev, info.err);
	SUSFS_LOGI("CMD_SUSFS_ADD_SUS_MOUNT -> ret: %d\n", info.err);
}
#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MOUNT

/* spoof_uname */
#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
static struct st_susfs_uname my_uname = {0};
DEFINE_STATIC_KEY_FALSE(susfs_is_uname_spoof_buffer_set);
static DEFINE_SEQLOCK(susfs_uname_seqlock);

void susfs_set_uname(void __user **user_info)
{
	struct st_susfs_uname info = {0};

	if (copy_from_user(&info, (struct st_susfs_uname __user *)*user_info, sizeof(info))) {
		info.err = -EFAULT;
		goto out_copy_to_user;
	}

	if (*info.release == '\0' || *info.version == '\0') {
		info.err = -EFAULT;
		goto out_copy_to_user;
	}

	write_seqlock(&susfs_uname_seqlock);
	if (!strcmp(info.release, "default")) {
		strscpy(my_uname.release, utsname()->release, __NEW_UTS_LEN);
	} else {
		strscpy(my_uname.release, info.release, __NEW_UTS_LEN);
	}
	if (!strcmp(info.version, "default")) {
		strscpy(my_uname.version, utsname()->version, __NEW_UTS_LEN);
	} else {
		strscpy(my_uname.version, info.version, __NEW_UTS_LEN);
	}
	write_sequnlock(&susfs_uname_seqlock);

	if (!static_key_enabled(&susfs_is_uname_spoof_buffer_set))
		static_branch_enable(&susfs_is_uname_spoof_buffer_set);

	SUSFS_LOGI("set spoofed release: '%s', version: '%s'\n",
			my_uname.release, my_uname.version);

	info.err = 0;
out_copy_to_user:
	if (copy_to_user(&((struct st_susfs_uname __user *)*user_info)->err, &info.err, sizeof(info.err))) {
		info.err = -EFAULT;
	}
	SUSFS_LOGI("CMD_SUSFS_SET_UNAME -> ret: %d\n", info.err);
}

void susfs_spoof_uname(struct new_utsname* tmp)
{
	unsigned seq;

	do {
		seq = read_seqbegin(&susfs_uname_seqlock);
		strscpy(tmp->release, my_uname.release, __NEW_UTS_LEN);
		strscpy(tmp->version, my_uname.version, __NEW_UTS_LEN);
	} while (read_seqretry(&susfs_uname_seqlock, seq));
}
#endif // #ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
